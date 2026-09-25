import http from 'k6/http'; import {check,sleep} from 'k6';
export const options={vus:5,duration:'30s'};
export default function(){const r=http.post('http://localhost:8080/v1/chat/completions',JSON.stringify({model:'mock-model',messages:[{role:'user',content:'health test'}],max_tokens:16}),{headers:{'Content-Type':'application/json'}});check(r,{'200':x=>x.status===200});sleep(.1)}
