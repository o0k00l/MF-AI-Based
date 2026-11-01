import shutil
shutil.copy2('core/math_engine.py', 'core/math_engine.py.backup3')
print('Backup created')

with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

print('File length:', len(content))

first_def = content.find('def build_fifo_tax_lots')
print('First def at:', first_def)

new_content = content[:first_def]

new_content += '''

@dataclass
class TaxLot:
    """A single purchase lot of a fund."""
    fund_id: str
    scheme_name: str
    folio: str
    purchase_date: date
    units: float
    nav: float
    cost: float
    source: str
    
    def holding_days(self, as_of: date) -> int:
        return (as_of - self.purchase_date).days
    
    def is_long_term(self, as_of: date, holding_months: int = 12) -> bool:
        return (as_of - self.purchase_date).days > 365
    
    def is_short_term(self, as_of: date) -> bool:
        return not self.is_long_term(as_of)

@dataclass
class TaxLotSummary:
    fund_id: str
    scheme_name: str
    total_units: float
    total_cost: float
    current_value: float
    unrealized_gain: float
    ltcg_units: float
    ltcg_gain: float
    stcg_units: float
    stcg_gain: float
    ltcg_tax: float
    stcg_tax: float
    ltcg_exemption_used: float
    stcg_exemption_used: float
'''

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Part 1 done')