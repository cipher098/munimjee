// The public page carries published presentation only, never private editor state.
import {themes} from './theme-config.js';
const limits={brand_tagline:80,hero_eyebrow:60,hero_headline:100,hero_intro:300,collection_heading:100,story_heading:100,story_body:1000};
const keys=['theme','palette',...Object.keys(limits),'show_story','show_categories'];
export function publishedDesign(store){
  const config=store.design??{theme:store.theme,palette:'forest',...Object.fromEntries(Object.keys(limits).map(key=>[key,''])),show_story:true,show_categories:true};
  if(!config||typeof config!=='object'||Array.isArray(config)||Object.keys(config).length!==keys.length||!keys.every(key=>Object.hasOwn(config,key))||!Object.hasOwn(themes,config.theme)||config.theme!==store.theme||!['rose','forest','indigo'].includes(config.palette)||!['show_story','show_categories'].every(key=>typeof config[key]==='boolean')||!Object.entries(limits).every(([key,max])=>typeof config[key]==='string'&&[...config[key]].length<=max&&!/[<>\x00-\x08\x0b-\x1f\x7f]/.test(config[key])))throw Error('Unsupported published design.');
  const defaults=themes[config.theme];
  return {...config,eyebrow:config.hero_eyebrow||defaults.eyebrow,headline:config.hero_headline||defaults.headline,intro:config.hero_intro||defaults.intro,collection:config.collection_heading||defaults.collection,storyHeading:config.story_heading||'Our story',storyBody:config.story_body||store.description};
}
export function applyDesignClass(design,documentRoot=document.documentElement){
  documentRoot.dataset.theme=design.theme;
  documentRoot.classList.remove('palette-rose','palette-forest','palette-indigo');
  documentRoot.classList.add(`palette-${design.palette}`);
}
