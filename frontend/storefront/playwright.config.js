import {defineConfig} from '@playwright/test';
const port=Number(process.env.STOREFRONT_TEST_PORT||4318);
const baseURL=`http://127.0.0.1:${port}`;
export default defineConfig({
 testDir:'./tests',testMatch:'**/*.spec.js',workers:1,fullyParallel:false,
 use:{baseURL,headless:true,launchOptions:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{},trace:'retain-on-failure'},
 webServer:{command:`PORT=${port} npm run dev`,url:baseURL,reuseExistingServer:!process.env.CI,timeout:10000},
});
