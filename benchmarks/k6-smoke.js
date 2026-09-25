import http from 'k6/http'; import {check,sleep} from 'k6';
export const options={vus:5,duration:'30s'};
const baseUrl=__ENV.AEGIS_BASE_URL || 'http://localhost:18080';
const apiKey=__ENV.AEGIS_API_KEY;
if(!apiKey){throw new Error('Set AEGIS_API_KEY before running k6');}
export default function(){const r=http.post(baseUrl + '/v1/chat/completions',JSON.stringify({model:'mock-model',messages:[{role:'user',content:'health test'}],max_tokens:16}),{headers:{'Content-Type':'application/json','Authorization':'Bearer ' + apiKey}});check(r,{'200':x=>x.status===200});sleep(.1)}
