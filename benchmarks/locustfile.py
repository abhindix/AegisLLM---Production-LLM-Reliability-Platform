import os
from locust import HttpUser, task, between
class AegisUser(HttpUser):
    wait_time=between(.05,.2)
    @task
    def chat(self):
        self.client.post('/v1/chat/completions',json={'model':'mock-model','messages':[{'role':'user','content':'Explain KV cache in one sentence.'}],'max_tokens':32},headers={'Authorization':'Bearer ' + os.getenv('AEGIS_API_KEY', 'change-me-aegis-api-key')})
