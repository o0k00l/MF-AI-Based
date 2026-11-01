# Append architectural corrections to math_engine.py
with open('core/math_engine.py', 'r') as f:
    current = f.read()

# Find the end of compute_fifo_tax_lots
end_idx = current.find('stagger_required = stagger_required')
if end_idx != -1:
    end_idx = current.find('\n    }', end_idx) + 4
    print(f'Found end at index {end_idx}')
    new_content = current[:end_idx]
    
    # Read corrections from file
    with open('corrections.txt', 'r') as f:
        corrections = f.read()
    
    new_content += corrections
    
    with open('core/math_engine.py', 'w') as f:
        f.write(new_content)
    print('Architectural corrections appended to math_engine.py')
else:
    print('Could not find end of compute_fifo_tax_lots')