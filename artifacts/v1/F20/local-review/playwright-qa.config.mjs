// QA-only port and tests. Does not reuse a running application server.
import original from '../../../../frontend/storefront/playwright.config.js';
import {fileURLToPath} from 'node:url';
const app=fileURLToPath(new URL('../../../../frontend/storefront/',import.meta.url));
export default {...original,testDir:app+'/tests',testMatch:'**/wave2*.spec.js',
 outputDir:fileURLToPath(new URL('./browser-output/',import.meta.url)),
 use:{...original.use,baseURL:'http://127.0.0.1:4319'},
 webServer:{...original.webServer,command:'npm run dev',env:{PORT:'4319'},cwd:app,url:'http://127.0.0.1:4319',reuseExistingServer:false}};
