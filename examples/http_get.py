from sim7000 import Sim7000
import json

s = Sim7000(2, 115200, 16, 17)

# clear buffer if needed
for i in range(10):
    if s.ping():
        break
    
s.init_network()

resp = s.http('https://httpbin.org/post', method='POST')

print("response status: {}".format(resp.status_code))

print(resp.text())