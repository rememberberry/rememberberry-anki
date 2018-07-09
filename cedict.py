import re

def load_cedict(filename):
    cedict = []
    with open(filename, 'r', encoding="utf-8") as f:
        for line in f:
            if line.startswith('#'):
                continue
            trad, simpl, pi, trans = re.match(r"(\S*) (\S*) \[(.*)\] \/(.*)\/", line).groups()
            trans = trans.split('/')
            trans = [t for t in trans if not t.startswith('see also ')]
            cedict.append((trad, simpl, pi, trans))
    return cedict

