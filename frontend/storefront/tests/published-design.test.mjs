import {test} from 'node:test';
import assert from 'node:assert/strict';
import {publishedDesign,applyDesignClass} from '../src/published-design.js';
import {themes} from '../src/theme-config.js';
const config=theme=>({theme,palette:'forest',brand_tagline:'',hero_eyebrow:'',hero_headline:'',hero_intro:'',collection_heading:'',story_heading:'',story_body:'',show_story:true,show_categories:true});
for(const theme of Object.keys(themes))test(`${theme} published design uses existing defaults and fixed class`,()=>{
 const store={theme,description:'Published store story',design:config(theme)},design=publishedDesign(store);
 assert.equal(design.headline,themes[theme].headline);assert.equal(design.intro,themes[theme].intro);assert.equal(design.collection,themes[theme].collection);assert.equal(design.storyBody,store.description);
 const removed=[],added=[],root={dataset:{},classList:{remove:(...values)=>removed.push(...values),add:value=>added.push(value)}};
 applyDesignClass(design,root);assert.equal(root.dataset.theme,theme);assert.deepEqual(removed,['palette-rose','palette-forest','palette-indigo']);assert.deepEqual(added,['palette-forest']);
 const edited=publishedDesign({...store,design:{...config(theme),hero_headline:'Published title',show_story:false,show_categories:false}});
 assert.equal(edited.headline,'Published title');assert.equal(edited.show_story,false);assert.equal(edited.show_categories,false);
});
for(const patch of [{palette:'red; color:blue'},{theme:'video'},{hero_headline:'<img>'},{hero_headline:{private:'secret'}},{css:'body{}'},{show_categories:1},{story_body:'bad\u0000text'}])test(`unvalidated published design rejects ${JSON.stringify(patch)}`,()=>{
 assert.throws(()=>publishedDesign({theme:'editorial',design:{...config('editorial'),...patch}}),/Unsupported published design/);
});
