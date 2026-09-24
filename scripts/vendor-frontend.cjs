// Reproduce the committed browser dependency without a runtime CDN request.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const destination = path.join(root, 'misra-frontend/js/vendor');
fs.mkdirSync(destination, { recursive: true });
fs.copyFileSync(path.join(root, 'node_modules/fuse.js/dist/fuse.min.js'), path.join(destination, 'fuse.min.js'));
fs.copyFileSync(path.join(root, 'node_modules/fuse.js/LICENSE'), path.join(destination, 'fuse.LICENSE'));
