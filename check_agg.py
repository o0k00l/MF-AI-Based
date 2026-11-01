import re
c = open('core/math_engine.py').read()
idx = c.find('return FiduciaryFactsPayload(')
if idx != -1:
    print('Found at:', idx)
    end_idx = c.find('def ', idx + 1)
    if end_idx == -1:
        end_idx = len(c)
    print(c[idx:end_idx])