import sched, time
from gpu_profiler import gpu_measure
s = sched.scheduler(time.time, time.sleep)

def do_something(sc): 
    gpu_stat = gpu_measure()
    for stat in gpu_stat['gpu']:
        print(stat)
    sc.enter(5, 1, do_something, (sc,))

s.enter(5, 1, do_something, (s,))
s.run()