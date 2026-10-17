import {defineConfig} from '@playwright/test';
export default defineConfig({
 testDir:'./tests',testMatch:'**/*.spec.js',workers:1,fullyParallel:false,
 use:{baseURL:'http://127.0.0.1:4317',headless:true,launchOptions:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{},trace:'retain-on-failure'},
 webServer:{command:'npm run dev',url:'http://127.0.0.1:4317',reuseExistingServer:!process.env.CI,timeout:10000},
});
