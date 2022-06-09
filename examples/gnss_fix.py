from sim7000 import Sim7000
import json
import time

s = Sim7000(2, 115200, 16, 17)

s.cmd('CGNSWARM')
s.gnss_enable(True)

t1 = time.time()
# wait for fix
while True:
    fix = s.get_gnss_fix()
    if fix:
        break
    time.sleep(5)


t2 = time.time()

for k,v in fix.__dict__.items():
  print("{}: {}".format(k, v))
  
print("Time elapsed to get a fix: {}s".format(t2-t1))
