/*! Firebase JS SDK v12.19.0 (Apache-2.0) — 랭귀지 스타터용 묶음 */
import{A as b,C as Z,D as ee,E as T,F as A,I as De,J as M,K as Fe,L as g,i as R,l as _,m as D,n as F,o as v,p as S,r as Q,w as O,x as C}from"./fb-shared-XC5M3KBE.js";var Oe="firebase",Me="12.19.0";g(Oe,Me,"app");var ie="@firebase/installations",L="0.6.24";var ae=1e4,re=`w:${L}`,se="FIS_v2",$e="https://firebaseinstallations.googleapis.com/v1",xe=3600*1e3,Ne="installations",Le="Installations";var qe={"missing-app-config-values":'Missing App configuration value: "{$valueName}"',"not-registered":"Firebase Installation is not registered.","installation-not-found":"Firebase Installation not found.","request-failed":'{$requestName} request failed with error "{$serverCode} {$serverStatus}: {$serverMessage}"',"app-offline":"Could not process request. Application offline.","delete-pending-registration":"Can't delete installation while there is a pending registration request."},w=new S(Ne,Le,qe);function oe(e){return e instanceof v&&e.code.includes("request-failed")}function ce({projectId:e}){return`${$e}/projects/${e}/installations`}function le(e){return{token:e.token,requestStatus:2,expiresIn:Ue(e.expiresIn),creationTime:Date.now()}}async function ue(e,t){let i=(await t.json()).error;return w.create("request-failed",{requestName:e,serverCode:i.code,serverMessage:i.message,serverStatus:i.status})}function de({apiKey:e}){return new Headers({"Content-Type":"application/json",Accept:"application/json","x-goog-api-key":e})}function je(e,{refreshToken:t}){let n=de(e);return n.append("Authorization",Be(t)),n}async function fe(e){let t=await e();return t.status>=500&&t.status<600?e():t}function Ue(e){return Number(e.replace("s","000"))}function Be(e){return`${se} ${e}`}async function Ve({appConfig:e,heartbeatServiceProvider:t},{fid:n}){let i=ce(e),a=de(e),r=t.getImmediate({optional:!0});if(r){let l=await r.getHeartbeatsHeader();l&&a.append("x-firebase-client",l)}let s={fid:n,authVersion:se,appId:e.appId,sdkVersion:re},o={method:"POST",headers:a,body:JSON.stringify(s)},c=await fe(()=>fetch(i,o));if(c.ok){let l=await c.json();return{fid:l.fid||n,registrationStatus:2,refreshToken:l.refreshToken,authToken:le(l.authToken)}}else throw await ue("Create Installation",c)}function pe(e){return new Promise(t=>{setTimeout(t,e)})}function ze(e){return btoa(String.fromCharCode(...e)).replace(/\+/g,"-").replace(/\//g,"_")}var Ge=/^[cdef][\w-]{21}$/,N="";function He(){try{let e=new Uint8Array(17);(self.crypto||self.msCrypto).getRandomValues(e),e[0]=112+e[0]%16;let n=Ke(e);return Ge.test(n)?n:N}catch{return N}}function Ke(e){return ze(e).substr(0,22)}function E(e){return`${e.appName}!${e.appId}`}var me=new Map;function ge(e,t){let n=E(e);he(n,t),We(n,t)}function he(e,t){let n=me.get(e);if(n)for(let i of n)i(t)}function We(e,t){let n=Ye();n&&n.postMessage({key:e,fid:t}),Je()}var h=null;function Ye(){return!h&&"BroadcastChannel"in self&&(h=new BroadcastChannel("[Firebase] FID Change"),h.onmessage=e=>{he(e.data.key,e.data.fid)}),h}function Je(){me.size===0&&h&&(h.close(),h=null)}var Xe="firebase-installations-database",Qe=1,I="firebase-installations-store",$=null;function q(){return $||($=ee(Xe,Qe,{upgrade:(e,t)=>{t===0&&e.createObjectStore(I)}})),$}async function k(e,t){let n=E(e),a=(await q()).transaction(I,"readwrite"),r=a.objectStore(I),s=await r.get(n);return await r.put(t,n),await a.done,(!s||s.fid!==t.fid)&&ge(e,t.fid),t}async function we(e){let t=E(e),i=(await q()).transaction(I,"readwrite");await i.objectStore(I).delete(t),await i.done}async function P(e,t){let n=E(e),a=(await q()).transaction(I,"readwrite"),r=a.objectStore(I),s=await r.get(n),o=t(s);return o===void 0?await r.delete(n):await r.put(o,n),await a.done,o&&(!s||s.fid!==o.fid)&&ge(e,o.fid),o}async function j(e){let t,n=await P(e.appConfig,i=>{let a=Ze(i),r=et(e,a);return t=r.registrationPromise,r.installationEntry});return n.fid===N?{installationEntry:await t}:{installationEntry:n,registrationPromise:t}}function Ze(e){let t=e||{fid:He(),registrationStatus:0};return Ie(t)}function et(e,t){if(t.registrationStatus===0){if(!navigator.onLine){let a=Promise.reject(w.create("app-offline"));return{installationEntry:t,registrationPromise:a}}let n={fid:t.fid,registrationStatus:1,registrationTime:Date.now()},i=tt(e,n);return{installationEntry:n,registrationPromise:i}}else return t.registrationStatus===1?{installationEntry:t,registrationPromise:nt(e)}:{installationEntry:t}}async function tt(e,t){try{let n=await Ve(e,t);return k(e.appConfig,n)}catch(n){throw oe(n)&&n.customData.serverCode===409?await we(e.appConfig):await k(e.appConfig,{fid:t.fid,registrationStatus:0}),n}}async function nt(e){let t=await te(e.appConfig);for(;t.registrationStatus===1;)await pe(100),t=await te(e.appConfig);if(t.registrationStatus===0){let{installationEntry:n,registrationPromise:i}=await j(e);return i||n}return t}function te(e){return P(e,t=>{if(!t)throw w.create("installation-not-found");return Ie(t)})}function Ie(e){return it(e)?{fid:e.fid,registrationStatus:0}:e}function it(e){return e.registrationStatus===1&&e.registrationTime+ae<Date.now()}async function at({appConfig:e,heartbeatServiceProvider:t},n){let i=rt(e,n),a=je(e,n),r=t.getImmediate({optional:!0});if(r){let l=await r.getHeartbeatsHeader();l&&a.append("x-firebase-client",l)}let s={installation:{sdkVersion:re,appId:e.appId}},o={method:"POST",headers:a,body:JSON.stringify(s)},c=await fe(()=>fetch(i,o));if(c.ok){let l=await c.json();return le(l)}else throw await ue("Generate Auth Token",c)}function rt(e,{fid:t}){return`${ce(e)}/${t}/authTokens:generate`}async function U(e,t=!1){let n,i=await P(e.appConfig,r=>{if(!ye(r))throw w.create("not-registered");let s=r.authToken;if(!t&&ct(s))return r;if(s.requestStatus===1)return n=st(e,t),r;{if(!navigator.onLine)throw w.create("app-offline");let o=ut(r);return n=ot(e,o),o}});return n?await n:i.authToken}async function st(e,t){let n=await ne(e.appConfig);for(;n.authToken.requestStatus===1;)await pe(100),n=await ne(e.appConfig);let i=n.authToken;return i.requestStatus===0?U(e,t):i}function ne(e){return P(e,t=>{if(!ye(t))throw w.create("not-registered");let n=t.authToken;return dt(n)?{...t,authToken:{requestStatus:0}}:t})}async function ot(e,t){try{let n=await at(e,t),i={...t,authToken:n};return await k(e.appConfig,i),n}catch(n){if(oe(n)&&(n.customData.serverCode===401||n.customData.serverCode===404))await we(e.appConfig);else{let i={...t,authToken:{requestStatus:0}};await k(e.appConfig,i)}throw n}}function ye(e){return e!==void 0&&e.registrationStatus===2}function ct(e){return e.requestStatus===2&&!lt(e)}function lt(e){let t=Date.now();return t<e.creationTime||e.creationTime+e.expiresIn<t+xe}function ut(e){let t={requestStatus:1,requestTime:Date.now()};return{...e,authToken:t}}function dt(e){return e.requestStatus===1&&e.requestTime+ae<Date.now()}async function ft(e){let t=e,{installationEntry:n,registrationPromise:i}=await j(t);return i?i.catch(console.error):U(t).catch(console.error),n.fid}async function pt(e,t=!1){let n=e;return await mt(n),(await U(n,t)).token}async function mt(e){let{registrationPromise:t}=await j(e);t&&await t}function gt(e){if(!e||!e.options)throw x("App Configuration");if(!e.name)throw x("App Name");let t=["projectId","apiKey","appId"];for(let n of t)if(!e.options[n])throw x(n);return{appName:e.name,projectId:e.options.projectId,apiKey:e.options.apiKey,appId:e.options.appId}}function x(e){return w.create("missing-app-config-values",{valueName:e})}var be="installations",ht="installations-internal",wt=e=>{let t=e.getProvider("app").getImmediate(),n=gt(t),i=A(t,"heartbeat");return{app:t,appConfig:n,heartbeatServiceProvider:i,_delete:()=>Promise.resolve()}},It=e=>{let t=e.getProvider("app").getImmediate(),n=A(t,be).getImmediate();return{getId:()=>ft(n),getToken:a=>pt(n,a)}};function yt(){T(new b(be,wt,"PUBLIC")),T(new b(ht,It,"PRIVATE"))}yt();g(ie,L);g(ie,L,"esm2020");var V="analytics",bt="firebase_id",Tt="origin",At=60*1e3,vt="https://firebase.googleapis.com/v1alpha/projects/-/apps/{app-id}/webConfig",Y="https://www.googletagmanager.com/gtag/js";var u=new Z("@firebase/analytics");var St={"already-exists":"A Firebase Analytics instance with the appId {$id}  already exists. Only one Firebase Analytics instance can be created for each appId.","already-initialized":"initializeAnalytics() cannot be called again with different options than those it was initially called with. It can be called again with the same options to return the existing instance, or getAnalytics() can be used to get a reference to the already-initialized instance.","already-initialized-settings":"Firebase Analytics has already been initialized.settings() must be called before initializing any Analytics instanceor it will have no effect.","interop-component-reg-failed":"Firebase Analytics Interop Component failed to instantiate: {$reason}","invalid-analytics-context":"Firebase Analytics is not supported in this environment. Wrap initialization of analytics in analytics.isSupported() to prevent initialization in unsupported environments. Details: {$errorInfo}","indexeddb-unavailable":"IndexedDB unavailable or restricted in this environment. Wrap initialization of analytics in analytics.isSupported() to prevent initialization in unsupported environments. Details: {$errorInfo}","fetch-throttle":"The config fetch request timed out while in an exponential backoff state. Unix timestamp in milliseconds when fetch request throttling ends: {$throttleEndTimeMillis}.","config-fetch-failed":"Dynamic config fetch failed: [{$httpStatus}] {$responseMessage}","no-api-key":'The "apiKey" field is empty in the local Firebase config. Firebase Analytics requires this field tocontain a valid API key.',"no-app-id":'The "appId" field is empty in the local Firebase config. Firebase Analytics requires this field tocontain a valid app ID.',"no-client-id":'The "client_id" field is empty.',"invalid-gtag-resource":"Trusted Types detected an invalid gtag resource: {$gtagURL}."},d=new S("analytics","Analytics",St);function Ct(e){if(!e.startsWith(Y)){let t=d.create("invalid-gtag-resource",{gtagURL:e});return u.warn(t.message),""}return e}function Ee(e){return Promise.all(e.map(t=>t.catch(n=>n)))}function kt(e,t){let n;return window.trustedTypes&&(n=window.trustedTypes.createPolicy(e,t)),n}function Et(e,t){let n=kt("firebase-js-sdk-policy",{createScriptURL:Ct}),i=document.createElement("script"),a=`${Y}?l=${e}&id=${t}`;i.src=n?n==null?void 0:n.createScriptURL(a):a,i.async=!0,document.head.appendChild(i)}function Pt(e){let t=[];return Array.isArray(window[e])?t=window[e]:window[e]=t,t}async function Rt(e,t,n,i,a,r){let s=i[a];try{if(s)await t[s];else{let c=(await Ee(n)).find(l=>l.measurementId===a);c&&await t[c.appId]}}catch(o){u.error(o)}e("config",a,r)}async function _t(e,t,n,i,a){try{let r=[];if(a&&a.send_to){let s=a.send_to;Array.isArray(s)||(s=[s]);let o=await Ee(n);for(let c of s){let l=o.find(p=>p.measurementId===c),f=l&&t[l.appId];if(f)r.push(f);else{r=[];break}}}r.length===0&&(r=Object.values(t)),await Promise.all(r),e("event",i,a||{})}catch(r){u.error(r)}}function Dt(e,t,n,i){async function a(r,...s){try{if(r==="event"){let[o,c]=s;await _t(e,t,n,o,c)}else if(r==="config"){let[o,c]=s;await Rt(e,t,n,i,o,c)}else if(r==="consent"){let[o,c]=s;e("consent",o,c)}else if(r==="get"){let[o,c,l]=s;e("get",o,c,l)}else if(r==="set"){let[o]=s;e("set",o)}else e(r,...s)}catch(o){u.error(o)}}return a}function Ft(e,t,n,i,a){let r=function(...s){window[i].push(arguments)};return window[a]&&typeof window[a]=="function"&&(r=window[a]),window[a]=Dt(r,e,t,n),{gtagCore:r,wrappedGtag:window[a]}}function Ot(e){let t=window.document.getElementsByTagName("script");for(let n of Object.values(t))if(n.src&&n.src.includes(Y)&&n.src.includes(e))return n;return null}var Mt=30,$t=1e3,z=class{constructor(t={},n=$t){this.throttleMetadata=t,this.intervalMillis=n}getThrottleMetadata(t){return this.throttleMetadata[t]}setThrottleMetadata(t,n){this.throttleMetadata[t]=n}deleteThrottleMetadata(t){delete this.throttleMetadata[t]}},Pe=new z;function xt(e){return new Headers({Accept:"application/json","x-goog-api-key":e})}async function Nt(e){var s;let{appId:t,apiKey:n}=e,i={method:"GET",headers:xt(n)},a=vt.replace("{app-id}",t),r=await fetch(a,i);if(r.status!==200&&r.status!==304){let o="";try{let c=await r.json();(s=c.error)!=null&&s.message&&(o=c.error.message)}catch{}throw d.create("config-fetch-failed",{httpStatus:r.status,responseMessage:o})}return r.json()}async function Lt(e,t=Pe,n){let{appId:i,apiKey:a,measurementId:r}=e.options;if(!i)throw d.create("no-app-id");if(!a){if(r)return{measurementId:r,appId:i};throw d.create("no-api-key")}let s=t.getThrottleMetadata(i)||{backoffCount:0,throttleEndTimeMillis:Date.now()},o=new G;return setTimeout(async()=>{o.abort()},At),Re({appId:i,apiKey:a,measurementId:r},s,o,t)}async function Re(e,{throttleEndTimeMillis:t,backoffCount:n},i,a=Pe){var o;let{appId:r,measurementId:s}=e;try{await qt(i,t)}catch(c){if(s)return u.warn(`Timed out fetching this Firebase app's measurement ID from the server. Falling back to the measurement ID ${s} provided in the "measurementId" field in the local Firebase config. [${c==null?void 0:c.message}]`),{appId:r,measurementId:s};throw c}try{let c=await Nt(e);return a.deleteThrottleMetadata(r),c}catch(c){let l=c;if(!jt(l)){if(a.deleteThrottleMetadata(r),s)return u.warn(`Failed to fetch this Firebase app's measurement ID from the server. Falling back to the measurement ID ${s} provided in the "measurementId" field in the local Firebase config. [${l==null?void 0:l.message}]`),{appId:r,measurementId:s};throw c}let f=Number((o=l==null?void 0:l.customData)==null?void 0:o.httpStatus)===503?O(n,a.intervalMillis,Mt):O(n,a.intervalMillis),p={throttleEndTimeMillis:Date.now()+f,backoffCount:n+1};return a.setThrottleMetadata(r,p),u.debug(`Calling attemptFetch again in ${f} millis`),Re(e,p,i,a)}}function qt(e,t){return new Promise((n,i)=>{let a=Math.max(t-Date.now(),0),r=setTimeout(n,a);e.addEventListener(()=>{clearTimeout(r),i(d.create("fetch-throttle",{throttleEndTimeMillis:t}))})})}function jt(e){if(!(e instanceof v)||!e.customData)return!1;let t=Number(e.customData.httpStatus);return t===429||t===500||t===503||t===504}var G=class{constructor(){this.listeners=[]}addEventListener(t){this.listeners.push(t)}abort(){this.listeners.forEach(t=>t())}};var H;async function Ut(e,t,n,i,a){if(a&&a.global){e("event",n,i);return}else{let r=await t,s={...i,send_to:r};e("event",n,s)}}async function Bt(e,t,n,i){if(i&&i.global){let a={};for(let r of Object.keys(n))a[`user_properties.${r}`]=n[r];return e("set",a),Promise.resolve()}else{let a=await t;e("config",a,{update:!0,user_properties:n})}}async function Vt(e,t){let n=await e;window[`ga-disable-${n}`]=!t}var K;function zt(e){K=e}function Gt(e){H=e}async function Ht(){if(_())try{await D()}catch(e){return u.warn(d.create("indexeddb-unavailable",{errorInfo:e==null?void 0:e.toString()}).message),!1}else return u.warn(d.create("indexeddb-unavailable",{errorInfo:"IndexedDB is not available in this environment."}).message),!1;return!0}async function Kt(e,t,n,i,a,r,s){var X;let o=Lt(e);o.then(m=>{n[m.measurementId]=m.appId,e.options.measurementId&&m.measurementId!==e.options.measurementId&&u.warn(`The measurement ID in the local Firebase config (${e.options.measurementId}) does not match the measurement ID fetched from the server (${m.measurementId}). To ensure analytics events are always sent to the correct Analytics property, update the measurement ID field in the local config or remove it from the local config.`)}).catch(m=>u.error(m)),t.push(o);let c=Ht().then(m=>{if(m)return i.getId()}),[l,f]=await Promise.all([o,c]);Ot(r)||Et(r,l.measurementId),K&&(a("consent","default",K),zt(void 0)),a("js",new Date);let p=(X=s==null?void 0:s.config)!=null?X:{};return p[Tt]="firebase",p.update=!0,f!=null&&(p[bt]=f),a("config",l.measurementId,p),H&&(a("set",H),Gt(void 0)),l.measurementId}var W=class{constructor(t){this.app=t}_delete(){return delete y[this.app.options.appId],Promise.resolve()}},y={},Te=[],Ae={},B="dataLayer",Wt="gtag",ve,J,Se=!1;function Yt(){let e=[];if(R()&&e.push("This is a browser extension environment."),F()||e.push("Cookies are not available."),e.length>0){let t=e.map((i,a)=>`(${a+1}) ${i}`).join(" "),n=d.create("invalid-analytics-context",{errorInfo:t});u.warn(n.message)}}function Jt(e,t,n){Yt();let i=e.options.appId;if(!i)throw d.create("no-app-id");if(!e.options.apiKey)if(e.options.measurementId)u.warn(`The "apiKey" field is empty in the local Firebase config. This is needed to fetch the latest measurement ID for this Firebase app. Falling back to the measurement ID ${e.options.measurementId} provided in the "measurementId" field in the local Firebase config.`);else throw d.create("no-api-key");if(y[i]!=null)throw d.create("already-exists",{id:i});if(!Se){Pt(B);let{wrappedGtag:r,gtagCore:s}=Ft(y,Te,Ae,B,Wt);J=r,ve=s,Se=!0}return y[i]=Kt(e,Te,Ae,t,ve,B,n),new W(e)}function Xt(e,t={}){let n=A(e,V);if(n.isInitialized()){let a=n.getImmediate();if(Q(t,n.getOptions()))return a;throw d.create("already-initialized")}return n.initialize({options:t})}async function Qt(){if(R()||!F()||!_())return!1;try{return await D()}catch{return!1}}function Zt(e,t,n){e=C(e),Bt(J,y[e.app.options.appId],t,n).catch(i=>u.error(i))}function en(e,t){e=C(e),Vt(y[e.app.options.appId],t).catch(n=>u.error(n))}function _e(e,t,n,i){e=C(e),Ut(J,y[e.app.options.appId],t,n,i).catch(a=>u.error(a))}var Ce="@firebase/analytics",ke="0.10.25";function tn(){T(new b(V,(t,{options:n})=>{let i=t.getProvider("app").getImmediate(),a=t.getProvider("installations-internal").getImmediate();return Jt(i,a,n)},"PUBLIC")),T(new b("analytics-internal",e,"PRIVATE")),g(Ce,ke),g(Ce,ke,"esm2020");function e(t){try{let n=t.getProvider(V).getImmediate();return{logEvent:(i,a,r)=>_e(n,i,a,r),setUserProperties:(i,a)=>Zt(n,i,a)}}catch(n){throw d.create("interop-component-reg-failed",{reason:n})}}}tn();export{Qt as analyticsSupported,M as getApp,Fe as getApps,Xt as initializeAnalytics,De as initializeApp,_e as logEvent,en as setAnalyticsCollectionEnabled};
/*! Bundled license information:

firebase/app/dist/esm/index.esm.js:
@firebase/installations/dist/esm/index.esm.js:
@firebase/analytics/dist/esm/index.esm.js:
  (**
   * @license
   * Copyright 2020 Google LLC
   *
   * Licensed under the Apache License, Version 2.0 (the "License");
   * you may not use this file except in compliance with the License.
   * You may obtain a copy of the License at
   *
   *   http://www.apache.org/licenses/LICENSE-2.0
   *
   * Unless required by applicable law or agreed to in writing, software
   * distributed under the License is distributed on an "AS IS" BASIS,
   * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   * See the License for the specific language governing permissions and
   * limitations under the License.
   *)

@firebase/installations/dist/esm/index.esm.js:
@firebase/installations/dist/esm/index.esm.js:
@firebase/installations/dist/esm/index.esm.js:
@firebase/installations/dist/esm/index.esm.js:
@firebase/analytics/dist/esm/index.esm.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   *
   * Licensed under the Apache License, Version 2.0 (the "License");
   * you may not use this file except in compliance with the License.
   * You may obtain a copy of the License at
   *
   *   http://www.apache.org/licenses/LICENSE-2.0
   *
   * Unless required by applicable law or agreed to in writing, software
   * distributed under the License is distributed on an "AS IS" BASIS,
   * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   * See the License for the specific language governing permissions and
   * limitations under the License.
   *)

@firebase/installations/dist/esm/index.esm.js:
@firebase/analytics/dist/esm/index.esm.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   *
   * Licensed under the Apache License, Version 2.0 (the "License");
   * you may not use this file except in compliance with the License.
   * You may obtain a copy of the License at
   *
   *   http://www.apache.org/licenses/LICENSE-2.0
   *
   * Unless required by applicable law or agreed to in writing, software
   * distributed under the License is distributed on an "AS IS" BASIS,
   * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   * See the License for the specific language governing permissions and
   * limitations under the License.
   *)
  (**
   * @license
   * Copyright 2020 Google LLC
   *
   * Licensed under the Apache License, Version 2.0 (the "License");
   * you may not use this file except in compliance with the License.
   * You may obtain a copy of the License at
   *
   *   http://www.apache.org/licenses/LICENSE-2.0
   *
   * Unless required by applicable law or agreed to in writing, software
   * distributed under the License is distributed on an "AS IS" BASIS,
   * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   * See the License for the specific language governing permissions and
   * limitations under the License.
   *)

@firebase/analytics/dist/esm/index.esm.js:
  (**
   * @license
   * Copyright 2020 Google LLC
   *
   * Licensed under the Apache License, Version 2.0 (the "License");
   * you may not use this file except in compliance with the License.
   * You may obtain a copy of the License at
   *
   *   http://www.apache.org/licenses/LICENSE-2.0
   *
   * Unless required by applicable law or agreed to in writing, software
   * distributed under the License is distributed on an "AS IS" BASIS,
   * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   * See the License for the specific language governing permissions and
   * limitations under the License.
   *)
  (**
   * @license
   * Copyright 2019 Google LLC
   *
   * Licensed under the Apache License, Version 2.0 (the "License");
   * you may not use this file except in compliance with the License.
   * You may obtain a copy of the License at
   *
   *   http://www.apache.org/licenses/LICENSE-2.0
   *
   * Unless required by applicable law or agreed to in writing, software
   * distributed under the License is distributed on an "AS IS" BASIS,
   * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   * See the License for the specific language governing permissions and
   * limitations under the License.
   *)
*/
