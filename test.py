from sim7000 import Sim7000
s = Sim7000(2, 115200)
s.init_network()
s.http_get('http://httpbin.org/get')