"""Build an account-free, evidence-linked reviewer tour from measured outputs."""
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]

def build():
    metrics = json.loads((ROOT/'artifacts/metrics.json').read_text())
    policies = pd.DataFrame(metrics['policies']).set_index('policy')
    fixed, pred = policies.loc['fixed_90_day'], policies.loc['predictive']
    general = pd.read_csv(ROOT/'reports/generalization_metrics.csv')
    external = general[(general.seed != 42)&(general.model=='published_reference_80_assets')]
    ai = json.loads((ROOT/'reports/assistant-evaluation.json').read_text())
    operations = pd.read_csv(ROOT/'reports/operations_policies.csv')
    values = {'savings': f"C${(fixed.total_cost_cad-pred.total_cost_cad)/pred.evaluation_years/1e6:.2f}M",
              'downtime': f"{100*(1-pred.unplanned_downtime_hours/fixed.unplanned_downtime_hours):.1f}%",
              'recall': f"{external.recall.min():.1%}–{external.recall.max():.1%}",
              'evals': f"{ai['passed']}/{ai['cases']}"}
    template = (ROOT/'web/portfolio.html').read_text(encoding='utf-8')
    for key, value in values.items():
        template = template.replace('{{'+key+'}}', value)
    assert '{{' not in template
    (ROOT/'reports/portfolio.html').write_text(template,encoding='utf-8')
    # Standard scientific plot: all declared reference-fleet results and both capacity policies.
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig, axes = plt.subplots(1,2,figsize=(12,4.4),layout='constrained')
    baseline = pd.read_csv(ROOT/'reports/test_models.csv')
    # Read the selected model's measured recall instead of maintaining a presentation constant.
    selected = baseline[baseline['algorithm']==metrics['selected_model']].iloc[0]
    labels=['Reference\nseed 42']+[f"New fleet\n{seed}" for seed in external.seed]
    recalls=[selected.recall]+external.recall.tolist()
    axes[0].bar(labels, [x*100 for x in recalls], color=['#17324D']+['#087F8C']*len(external),width=.6)
    axes[0].set_ylim(0,100); axes[0].set_ylabel('Recall on labeled asset-days (%)')
    axes[0].set_title('Generalization exposes missed failures',loc='left',weight='bold')
    for i,value in enumerate(recalls): axes[0].text(i,value*100+2,f'{value:.1%}',ha='center')
    subset=operations[(operations.dispatch_delay_days==2)&(operations.policy!='reactive')]
    for name,color,label in [('fixed_90_day','#B7791F','Fixed 90-day'),('predictive','#087F8C','Predictive')]:
        series=subset[subset.policy==name].sort_values('weekly_capacity')
        axes[1].plot(range(len(series)),series.caught_failures,'o-',color=color,label=label,linewidth=2)
    axes[1].set_xticks(range(4),['3','5','10','Unconstrained']); axes[1].set_ylim(0,44)
    axes[1].set_xlabel('Planned visits available per week'); axes[1].set_ylabel('Failures prevented out of 44')
    axes[1].set_title('Crew capacity changes prevention',loc='left',weight='bold')
    axes[1].legend(frameon=False)
    fig.supxlabel('Synthetic study · fixed recipes and thresholds · two-day dispatch in capacity chart',fontsize=9,color='#526579')
    fig.savefig(ROOT/'reports/figures/portfolio_evidence.png',dpi=160,facecolor='white')
    plt.close(fig)
    return values

if __name__=='__main__':
    print(json.dumps(build(),indent=2))
