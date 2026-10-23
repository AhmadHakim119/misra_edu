/* Saved-study discovery for native screens. These are not live submissions. */
(function(){
  'use strict';
  async function load(){
    const catalog=await MisraAPI.pilotStudies();
    if(!Array.isArray(catalog?.items))throw Error('Saved pilot list is unavailable.');
    const items=await Promise.all(catalog.items.map(async entry=>{
      try{
        const study=await MisraAPI.pilotStudy(entry.study_id);
        if(!Array.isArray(study?.papers))throw Error('Saved paper list is incomplete.');
        const groups=new Map();
        for(const paper of study.papers){
          if(typeof paper.exam_id!=='string'||typeof paper.review?.needs_review!=='boolean')throw Error('Saved paper review status is incomplete.');
          if(!groups.has(paper.exam_id))groups.set(paper.exam_id,{exam_id:paper.exam_id,exam_version:paper.exam_version,paper_count:0,review_count:0});
          const group=groups.get(paper.exam_id);group.paper_count++;group.review_count+=Number(paper.review.needs_review);
        }
        return {...entry,title:study.title||entry.title,exams:[...groups.values()]};
      }catch(error){return {...entry,exams:null,error:'Saved paper counts could not load. Open the saved study to retry.'};}
    }));
    return {items};
  }
  function forExam(catalog,id){
    for(const study of catalog?.items||[]){
      const exam=study.exams?.find(row=>row.exam_id===id);
      if(exam)return {...exam,study_id:study.study_id};
      if(!study.exams&&study.exam_ids?.includes(id))return {exam_id:id,study_id:study.study_id,paper_count:null,review_count:null};
    }
    return null;
  }
  function href(studyId,examId,reviewOnly=false){
    const params=new URLSearchParams({study_id:studyId});
    if(examId)params.set('exam_id',examId);
    if(reviewOnly)params.set('needs_review','1');
    return 'pilot.html?'+params;
  }
  window.MisraPilots={load,forExam,href};
})();
