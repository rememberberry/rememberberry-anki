import re

cedict = {}
with open('sources/cedict_ts.u8', 'r') as f:
    i = 0
    for line in f:
        if line.startswith('#'):
            continue
        z = re.match(r"(\S*) (\S*) \[(.*)\] \/(.*)\/", line)
        print(z.groups())
        if i > 100:
            break
        i+=1


