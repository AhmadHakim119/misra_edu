"""Destructive recovery checks confined to newly created synthetic instances.

Never reads application credentials or connects to an existing service. Run
mysql mode with the existing MariaDB bin directory; redis mode inside WSL.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


def port():
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', 0))
        return stream.getsockname()[1]


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, timeout=60,
                          stderr=subprocess.PIPE, **kwargs)


def wait(check):
    for _ in range(100):
        try:
            return check()
        except Exception:
            time.sleep(.1)
    raise RuntimeError('Isolated service did not become ready')


def mysql_drill(directory, binary):
    import pymysql
    import shutil
    from pypdf import PdfWriter, PdfReader
    from sqlalchemy import create_engine, text
    directory, binary = Path(directory), Path(binary).resolve()
    data = directory/'data'
    listen = port()
    run([binary/'mysql_install_db.exe', '--datadir='+str(data), '--port='+str(listen)], stdout=subprocess.PIPE)
    args = [str(binary/'mysqld.exe'), '--no-defaults', '--basedir='+str(binary.parent),
            '--datadir='+str(data), '--port='+str(listen), '--bind-address=127.0.0.1',
            '--skip-name-resolve', '--skip-log-bin']
    process = None
    engine = None
    def connect():
        return pymysql.connect(host='127.0.0.1', port=listen, user='root', connect_timeout=2)
    def start():
        nonlocal process
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        connection = wait(connect)
        connection.close()
    def snapshot(name):
        with engine.connect() as connection:
            tables = connection.execute(text(f'SHOW TABLES FROM `{name}`')).scalars().all()
            result = {}
            for table in tables:
                rows = connection.execute(text(f'SELECT * FROM `{name}`.`{table}`')).all()
                result[table] = sorted(json.dumps(list(row), default=str, sort_keys=True) for row in rows)
            return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(), len(tables)
    try:
        start()
        connection = connect()
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE misra_drill CHARACTER SET utf8mb4')
            cursor.execute('CREATE DATABASE misra_restored CHARACTER SET utf8mb4')
        connection.close()
        os.environ['DB_URL'] = 'sqlite://'
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'misra_backend'))
        from database import Base
        from models import (Institution, User, Course, Exam, Question, RubricVersion,
                            Submission, Answer, GradingRun, ReviewLabel, ProcessingJob)
        from sqlalchemy.orm import Session
        original_paper = directory/'synthetic-paper.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=100,height=100)
        writer.add_blank_page(width=100,height=100)
        writer.write(original_paper)
        paper_hash = hashlib.sha256(original_paper.read_bytes()).hexdigest()
        shutil.copyfile(original_paper,directory/'paper-backup.pdf')
        engine = create_engine(f'mysql+pymysql://root@127.0.0.1:{listen}/misra_drill')
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(Institution(id='drill-institution', name='Synthetic recovery institution'))
            db.flush()
            db.add(User(id='drill-user', institution_id='drill-institution', email='drill@example.invalid',
                        hashed_password='synthetic-no-login', role='teacher'))
            db.flush()
            db.add(Course(id='drill-course', institution_id='drill-institution', teacher_id='drill-user',
                          course_code='SYN', title='Synthetic course'))
            db.flush()
            db.add(Exam(id='drill-exam', institution_id='drill-institution', course_id='drill-course', title='Synthetic exam'))
            db.flush()
            rubric = {'max_score':2,'criteria':[{'id':'method','description':'Synthetic method','points':2}]}
            db.add(Question(id='drill-question', institution_id='drill-institution', exam_id='drill-exam',
                            question_number='1',question_text='Synthetic question',max_score=2,rubric_json=rubric,order_index=0))
            db.add(Submission(id='drill-paper', institution_id='drill-institution', exam_id='drill-exam',
                              original_file_path=str(original_paper),page_count=2,status='reviewed'))
            db.flush()
            db.add(RubricVersion(id='drill-rubric',question_id='drill-question',version_number=1,status='approved',rubric_json=rubric))
            db.add(Answer(id='drill-answer',institution_id='drill-institution',submission_id='drill-paper',
                          question_id='drill-question',raw_ocr_text='Synthetic work',score=1,max_score=2,
                          teacher_override_score=2,review_status='overridden',needs_review=False,
                          grading_raw_response={'grading_run_id':'drill-run','applied_review_label_id':'drill-label'}))
            db.flush()
            db.add(GradingRun(id='drill-run',answer_id='drill-answer',rubric_version_id='drill-rubric',
                              model_name='synthetic-no-provider',mode='text_only',score=1,max_score=2,
                              prompt_version='synthetic',ocr_text_snapshot='Synthetic work',feedback='Synthetic feedback',
                              reasoning='Synthetic reasoning',llm_confidence=50,final_confidence=50,
                              needs_review=True,criteria_scores=[{'criterion_id':'method','points_earned':1,'max_points':2}],
                              response_json={'synthetic':True},rubric_snapshot=rubric))
            db.flush()
            db.add(ReviewLabel(id='drill-label',answer_id='drill-answer',grading_run_id='drill-run',
                               ai_score_snapshot=1,human_score=2,was_review_warranted=True,labeled_by='drill-user'))
            db.add(ProcessingJob(id='drill-job',institution_id='drill-institution',requested_by='drill-user',
                                 submission_id='drill-paper',job_type='grade_submission',status='completed',payload={'synthetic':True}))
            db.commit()
        original, count = snapshot('misra_drill')
        backup = directory/'synthetic.sql'
        with backup.open('wb') as output:
            run([binary/'mysqldump.exe', '--no-defaults', '--host=127.0.0.1', '--port='+str(listen),
                 '--user=root', '--single-transaction', '--skip-comments', 'misra_drill'], stdout=output)
        with backup.open('rb') as source:
            run([binary/'mysql.exe', '--no-defaults', '--host=127.0.0.1', '--port='+str(listen),
                 '--user=root', 'misra_restored'], stdin=source, stdout=subprocess.PIPE)
        restored, _ = snapshot('misra_restored')
        assert original == restored, 'Restored schema/data differs'
        original_paper.write_bytes(b'synthetic simulated corruption')
        shutil.copyfile(directory/'paper-backup.pdf',original_paper)
        assert hashlib.sha256(original_paper.read_bytes()).hexdigest() == paper_hash
        assert len(PdfReader(original_paper).pages) == 2, 'Original pages changed during restore'
        engine.dispose()
        process.kill()  # Simulate loss of the isolated server, not a live instance.
        process.wait(timeout=15)
        start()
        restarted, _ = snapshot('misra_drill')
        assert restarted == original, 'Committed data changed after crash recovery'
        return {'service':'MariaDB', 'tables_checked':count, 'backup_restore':'pass',
                'original_page_restore':'pass','crash_restart':'pass'}
    finally:
        if engine is not None:
            engine.dispose()
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)


def redis_drill(directory):
    listen = port()
    args = ['redis-server', '--bind', '127.0.0.1', '--port', str(listen), '--dir', str(directory),
            '--appendonly', 'yes', '--appendfsync', 'always', '--save', '']
    def cli(*arguments):
        return run(['redis-cli','-h','127.0.0.1','-p',str(listen),'--raw',*arguments], stdout=subprocess.PIPE).stdout.decode().strip()
    def ready():
        if cli('PING') != 'PONG':
            raise RuntimeError('Not ready')
    process = None
    try:
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(ready)
        assert cli('RPUSH','misra:synthetic:queue','synthetic-job') == '1'
        process.kill()
        process.wait(timeout=15)
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(ready)
        assert cli('LPOP','misra:synthetic:queue') == 'synthetic-job'
        assert cli('LLEN','misra:synthetic:queue') == '0'
        return {'service':'Redis','aof_crash_recovery':'pass', 'synthetic_queue_consumption':'pass',
                'limit':'This checks Redis persistence, not RQ worker execution.'}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)


def rq_drill(directory):
    """Run an actual MISRA material job via real Redis/RQ, without a provider."""
    from redis import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    from redis.exceptions import ConnectionError
    from rq import Queue
    from rq.serializers import JSONSerializer
    from unittest.mock import patch
    listen = port()
    linux_dir = run(['wsl','-d','Ubuntu','--','wslpath','-a',Path(directory).as_posix()], stdout=subprocess.PIPE).stdout.decode().strip()
    process = subprocess.Popen(['wsl','-d','Ubuntu','--','redis-server','--bind','127.0.0.1',
        '--port',str(listen),'--dir',linux_dir,'--save','','--appendonly','no'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    connection = Redis(host='127.0.0.1', port=listen, socket_connect_timeout=1, socket_timeout=2,
                       retry=Retry(NoBackoff(), 0))
    owned = False
    fixture = None
    try:
        wait(connection.ping)
        actual_dir = connection.config_get('dir')['dir']
        if isinstance(actual_dir, bytes):
            actual_dir = actual_dir.decode()
        assert actual_dir == linux_dir, 'Unexpected Redis instance'
        owned = True
        os.environ['DB_URL'] = 'sqlite://'
        os.environ.setdefault('GEMINI_API_KEY', 'synthetic-never-used')
        os.environ['REDIS_URL'] = f'redis://127.0.0.1:{listen}/0'
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'misra_backend'))
        from tests import test_course_materials as fixtures
        from models import ProcessingJob
        from sqlalchemy.orm import sessionmaker
        from services.job_queue_service import dispatch_processing_job
        from worker import WindowsSimpleWorker
        fixture = fixtures.CourseMaterialTests()
        fixture.setUp()
        version, job = fixture.upload_pdf()
        dispatch_processing_job(job, fixture.db)
        assert job.status == 'queued' and job.rq_job_id
        # A worker crash before consumption must leave the queued job recoverable.
        queues = [Queue('ocr', connection=connection, serializer=JSONSerializer)]
        factory = sessionmaker(bind=fixture.engine)
        with patch('services.job_execution_service.SessionLocal', factory), \
             patch('services.gemini_client.generate', side_effect=AssertionError('Provider forbidden')):
            worker = WindowsSimpleWorker(queues, connection=connection, serializer=JSONSerializer)
            worker.work(burst=True, with_scheduler=False, logging_level='ERROR')
        fixture.db.expire_all()
        assert fixture.db.get(ProcessingJob, job.id).status == 'completed', 'MISRA worker did not complete'
        assert connection.llen('rq:queue:ocr') == 0
        return {'service':'MISRA Redis/RQ worker','synthetic_material_job':'completed',
                'provider_calls':0,'database':'isolated SQLite','limit':'Not a MariaDB+RQ concurrent fault drill.'}
    finally:
        if fixture is not None:
            fixture.tearDown()
            fixture.doCleanups()
        if owned:
            try:
                connection.execute_command('SHUTDOWN','NOSAVE')
            except ConnectionError:
                pass  # Redis closes the socket on successful shutdown.
        connection.close()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=['mysql','redis','rq'])
    parser.add_argument('--mysql-bin', type=Path)
    options = parser.parse_args()
    # TemporaryDirectory only owns a freshly created OS-temp child. It never
    # receives a user-selected data path or an existing application directory.
    with tempfile.TemporaryDirectory(prefix='misra-synthetic-recovery-') as location:
        assert Path(location).resolve().parent == Path(tempfile.gettempdir()).resolve()
        if options.service == 'mysql' and options.mysql_bin is None:
            parser.error('--mysql-bin is required for mysql mode')
        result = (mysql_drill(location, options.mysql_bin) if options.service == 'mysql'
                  else rq_drill(location) if options.service == 'rq' else redis_drill(location))
        print(json.dumps(result))
