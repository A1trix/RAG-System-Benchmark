#!/usr/bin/env python3
"""
Generate LaTeX tables from benchmark analysis data.
Creates 5 academic-style tables for thesis integration.
Uses only Python standard library (no pandas dependency).
Includes row numbers and split validity tables.
"""

import csv
import json
from pathlib import Path
from collections import defaultdict

# Paths
RESULTS_DIR = Path("/home/htrius/bachelor/bench/results/compare_20260324T160059Z")
ANALYSIS_DIR = RESULTS_DIR / "analysis"
OUTPUT_DIR = RESULTS_DIR / "tables"

def read_csv_dict(filename):
    """Read CSV file into list of dictionaries."""
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        return list(reader)

def read_csv_agg(filename):
    """Read aggregated CSV with many columns."""
    with open(filename, 'r') as f:
        lines = f.readlines()
        if len(lines) < 2:
            return []
        
        headers = lines[0].strip().split(',')
        
        data = []
        for line in lines[1:]:
            values = line.strip().split(',')
            if len(values) >= len(headers):
                row = dict(zip(headers, values))
                data.append(row)
        
        return data

def load_data():
    """Load all necessary data files using standard library only."""
    data = {}
    
    data['sweep_agg'] = read_csv_agg(ANALYSIS_DIR / "sweep_points_agg.csv")
    data['sweep_detail'] = read_csv_dict(ANALYSIS_DIR / "sweep_points.csv")
    data['invalid'] = read_csv_dict(ANALYSIS_DIR / "invalid_points.csv")
    
    with open(ANALYSIS_DIR / "pair_comparison.json") as f:
        data['pair_comp'] = json.load(f)
    
    for rep in ['rep01', 'rep02', 'rep03']:
        rag_file = RESULTS_DIR / f"children/{rep}-rag/analysis/sweep_points.csv"
        if rag_file.exists():
            data[f'rag_{rep}'] = read_csv_dict(rag_file)
    
    return data

def safe_float(value, default=None):
    """Safely convert to float."""
    if value is None or value == '' or value == '-':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value, default=None):
    """Safely convert to int."""
    if value is None or value == '' or value == '-':
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default

def create_valid_comparison_table(data):
    """Table 1: Valid Comparison Summary (10-20 RPM) with individual repetition data and row numbers."""
    
    rows = []
    
    # Get n8n data
    for row in data['sweep_detail']:
        if row.get('endpoint') == 'n8n':
            rpm = safe_int(row.get('offered_rpm'))
            if rpm in [10, 20]:
                rep = safe_int(row.get('rep'))
                
                throughput = safe_float(row.get('throughput_success_rps'))
                p95_lat = safe_float(row.get('latency_p95_s'))
                timeout_rate = safe_float(row.get('timeout_rate'))
                error_rate = safe_float(row.get('error_rate_total'))
                valid_str = row.get('rep_valid', 'False')
                valid = valid_str.lower() == 'true' if valid_str else False
                
                rows.append({
                    'rpm': rpm,
                    'system': 'n8n',
                    'rep': rep,
                    'throughput': f"{throughput:.3f}" if throughput is not None else '-',
                    'p95_lat': f"{p95_lat:.1f}" if p95_lat is not None else '-',
                    'timeout': f"{timeout_rate*100:.1f}" if timeout_rate is not None else '-',
                    'error': f"{error_rate*100:.1f}" if error_rate is not None else '-',
                    'valid': r'\checkmark' if valid else r'$\times$'
                })
    
    # Get RAG data from children
    for rep_num in [1, 2, 3]:
        key = f'rag_rep{rep_num:02d}'
        if key in data:
            for row in data[key]:
                rpm = safe_int(row.get('offered_rpm'))
                if rpm in [10, 20]:
                    throughput = safe_float(row.get('throughput_success_rps'))
                    p95_lat = safe_float(row.get('latency_p95_s'))
                    timeout_rate = safe_float(row.get('timeout_rate'))
                    error_rate = safe_float(row.get('error_rate_total'))
                    valid_str = row.get('rep_valid', 'False')
                    invalid_reasons = row.get('invalid_reasons', '')
                    valid = valid_str.lower() == 'true' if valid_str else False
                    if invalid_reasons and invalid_reasons.strip():
                        valid = False
                    
                    rows.append({
                        'rpm': rpm,
                        'system': 'RAG',
                        'rep': rep_num,
                        'throughput': f"{throughput:.3f}" if throughput is not None else '-',
                        'p95_lat': f"{p95_lat:.1f}" if p95_lat is not None else '-',
                        'timeout': f"{timeout_rate*100:.1f}" if timeout_rate is not None else '-',
                        'error': f"{error_rate*100:.1f}" if error_rate is not None else '-',
                        'valid': r'\checkmark' if valid else r'$\times$'
                    })
    
    rows.sort(key=lambda x: (x['rpm'], x['system'], x['rep']))
    
    # Generate LaTeX with row numbers
    latex = [
        r"\begin{tabular}{cccrrrrrc}",
        r"\toprule",
        r"\textbf{\#} & \textbf{RPM} & \textbf{System} & \textbf{Rep} & \textbf{Throughput} & \textbf{P95 Lat.} & \textbf{Timeout} & \textbf{Error} & \textbf{Valid} \\",
        r" & & & & \textbf{(rps)} & \textbf{(s)} & \textbf{(\%)} & \textbf{(\%)} & \\",
        r"\midrule"
    ]
    
    for i, row in enumerate(rows, 1):
        latex.append(
            f"{i} & {row['rpm']} & {row['system']} & {row['rep']} & "
            f"{row['throughput']} & {row['p95_lat']} & "
            f"{row['timeout']} & {row['error']} & {row['valid']} \\\\"
        )
    
    latex.extend([
        r"\bottomrule",
        r"\end{tabular}"
    ])
    
    output_file = OUTPUT_DIR / "table1_valid_comparison.tex"
    with open(output_file, 'w') as f:
        f.write('\n'.join(latex))
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_n8n_validity_table(data):
    """Table 2a: n8n Validity Overview with row numbers."""
    
    rpms = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    
    # Get n8n validity
    n8n_validity = {}
    for row in data['sweep_detail']:
        if row.get('endpoint') == 'n8n':
            rpm = safe_int(row.get('offered_rpm'))
            rep = safe_int(row.get('rep'))
            if rpm and rep:
                valid_str = row.get('rep_valid', 'False')
                n8n_validity[(rep, rpm)] = valid_str.lower() == 'true' if valid_str else False
    
    latex = [
        r"\begin{tabular}{cccccc}",
        r"\toprule",
        r"\textbf{\#} & \textbf{RPM} & \textbf{R1} & \textbf{R2} & \textbf{R3} & \textbf{Point} \\",
        r"\midrule"
    ]
    
    for i, rpm in enumerate(rpms, 1):
        row_parts = [str(i), str(rpm)]
        
        # n8n reps
        reps_valid = []
        for rep in [1, 2, 3]:
            valid = n8n_validity.get((rep, rpm), False)
            reps_valid.append(valid)
            row_parts.append(r'\cellcolor{validgreen}\checkmark' if valid else r'\cellcolor{invalidred}$\times$')
        
        # n8n point valid
        point_valid = all(reps_valid)
        row_parts.append(r'\cellcolor{validgreen}\checkmark' if point_valid else r'\cellcolor{invalidred}$\times$')
        
        latex.append(' & '.join(row_parts) + r' \\')
    
    latex.extend([
        r"\bottomrule",
        r"\end{tabular}"
    ])
    
    output_file = OUTPUT_DIR / "table2a_n8n_validity.tex"
    with open(output_file, 'w') as f:
        f.write('\n'.join(latex))
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_rag_validity_table(data):
    """Table 2b: RAG Validity Overview with row numbers."""
    
    rpms = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    
    # Get RAG validity
    rag_validity = {}
    for rep_num in [1, 2, 3]:
        key = f'rag_rep{rep_num:02d}'
        if key in data:
            for row in data[key]:
                rpm = safe_int(row.get('offered_rpm'))
                if rpm:
                    valid_str = row.get('rep_valid', 'False')
                    invalid_reasons = row.get('invalid_reasons', '')
                    is_valid = valid_str.lower() == 'true' if valid_str else False
                    # Check for invalid reasons
                    if invalid_reasons and invalid_reasons.strip():
                        is_valid = False
                    rag_validity[(rep_num, rpm)] = is_valid
    
    latex = [
        r"\begin{tabular}{cccccc}",
        r"\toprule",
        r"\textbf{\#} & \textbf{RPM} & \textbf{R1} & \textbf{R2} & \textbf{R3} & \textbf{Point} \\",
        r"\midrule"
    ]
    
    for i, rpm in enumerate(rpms, 1):
        row_parts = [str(i), str(rpm)]
        
        # RAG reps
        reps_valid = []
        for rep in [1, 2, 3]:
            valid = rag_validity.get((rep, rpm), False)
            reps_valid.append(valid)
            row_parts.append(r'\cellcolor{validgreen}\checkmark' if valid else r'\cellcolor{invalidred}$\times$')
        
        # RAG point valid
        point_valid = all(reps_valid)
        row_parts.append(r'\cellcolor{validgreen}\checkmark' if point_valid else r'\cellcolor{invalidred}$\times$')
        
        latex.append(' & '.join(row_parts) + r' \\')
    
    latex.extend([
        r"\bottomrule",
        r"\end{tabular}"
    ])
    
    output_file = OUTPUT_DIR / "table2b_rag_validity.tex"
    with open(output_file, 'w') as f:
        f.write('\n'.join(latex))
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_n8n_performance_table(data):
    """Table 3: Full n8n Performance with confidence intervals and row numbers."""
    
    n8n_agg = [row for row in data['sweep_agg'] if row.get('endpoint') == 'n8n']
    
    latex = [
        r"\begin{tabular}{ccccccrrc}",
        r"\toprule",
        r"\textbf{\#} & \textbf{RPM} & \textbf{Reps} & \textbf{Valid} & \textbf{Throughput} & \textbf{95\% CI} & \textbf{P95 Lat.} & \textbf{95\% CI} & \textbf{Prompt} \\",
        r" & & & & \textbf{(rps)} & & \textbf{(s)} & & $\Delta$ \\",
        r"\midrule"
    ]
    
    for i, row in enumerate(n8n_agg, 1):
        rpm = safe_int(row.get('offered_rpm'))
        reps = safe_int(row.get('reps'))
        point_valid_str = row.get('point_valid', 'False')
        point_valid = point_valid_str.lower() == 'true' if point_valid_str else False
        
        # Throughput with CI
        thr_mean = safe_float(row.get('throughput_success_rps_mean'))
        thr_ci_lo = safe_float(row.get('throughput_success_rps_ci95_lo'))
        thr_ci_hi = safe_float(row.get('throughput_success_rps_ci95_hi'))
        
        if thr_mean is not None:
            thr_str = f"{thr_mean:.3f}"
            ci_str = f"[{thr_ci_lo:.3f}, {thr_ci_hi:.3f}]" if thr_ci_lo is not None and thr_ci_hi is not None else '-'
        else:
            thr_str = '-'
            ci_str = '-'
        
        # P95 Latency with CI
        lat_mean = safe_float(row.get('latency_p95_s_mean'))
        lat_ci_lo = safe_float(row.get('latency_p95_s_ci95_lo'))
        lat_ci_hi = safe_float(row.get('latency_p95_s_ci95_hi'))
        
        if lat_mean is not None:
            lat_str = f"{lat_mean:.1f}"
            lat_ci_str = f"[{lat_ci_lo:.1f}, {lat_ci_hi:.1f}]" if lat_ci_lo is not None and lat_ci_hi is not None else '-'
        else:
            lat_str = '-'
            lat_ci_str = '-'
        
        # Prompt mix
        pm = safe_float(row.get('prompt_mix_max_minus_min_mean'))
        pm_str = f"{pm:.0f}" if pm is not None else '-'
        
        valid_str = r'\checkmark' if point_valid else r'$\times$'
        
        latex.append(
            f"{i} & {rpm} & {reps} & {valid_str} & {thr_str} & {ci_str} & "
            f"{lat_str} & {lat_ci_str} & {pm_str} \\\\"
        )
    
    latex.extend([
        r"\bottomrule",
        r"\end{tabular}"
    ])
    
    output_file = OUTPUT_DIR / "table3_n8n_performance.tex"
    with open(output_file, 'w') as f:
        f.write('\n'.join(latex))
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_rag_performance_table(data):
    """Table 4: RAG Performance with row numbers."""
    
    all_rag = []
    for rep_num in [1, 2, 3]:
        key = f'rag_rep{rep_num:02d}'
        if key in data:
            for row in data[key]:
                valid_str = row.get('rep_valid', 'False')
                invalid_reasons = row.get('invalid_reasons', '')
                is_valid = valid_str.lower() == 'true' if valid_str else False
                if invalid_reasons and invalid_reasons.strip():
                    is_valid = False
                
                all_rag.append({
                    'rep': rep_num,
                    'rpm': safe_int(row.get('offered_rpm')),
                    'throughput': safe_float(row.get('throughput_success_rps')),
                    'p95_lat': safe_float(row.get('latency_p95_s')),
                    'timeout_rate': safe_float(row.get('timeout_rate')),
                    'prompt_diff': safe_float(row.get('prompt_mix_max_minus_min')),
                    'dropped': safe_int(row.get('dropped_iterations_count'), 0),
                    'valid': is_valid
                })
    
    if not all_rag:
        print("  Warning: No RAG data found, skipping table 4")
        return None
    
    rpm_data = defaultdict(list)
    for row in all_rag:
        if row['rpm']:
            rpm_data[row['rpm']].append(row)
    
    latex = [
        r"\begin{tabular}{ccccrrrrrc}",
        r"\toprule",
        r"\textbf{\#} & \textbf{RPM} & \textbf{Valid} & \textbf{Throughput} & \textbf{P95 Lat.} & \textbf{Timeout} & \textbf{Prompt} & \textbf{Dropped} & \textbf{Status} \\",
        r" & & \textbf{Reps} & \textbf{(rps)} & \textbf{(s)} & \textbf{(\%)} & $\Delta$ & \textbf{Iters} & \\",
        r"\midrule"
    ]
    
    for i, rpm in enumerate(sorted(rpm_data.keys()), 1):
        rpm_rows = rpm_data[rpm]
        valid_reps = [r for r in rpm_rows if r['valid']]
        
        valid_count = f"{len(valid_reps)}/3"
        
        # Throughput (mean of valid reps)
        valid_thr = [r['throughput'] for r in valid_reps if r['throughput'] is not None]
        if valid_thr:
            thr_str = f"{sum(valid_thr)/len(valid_thr):.3f}"
        else:
            thr_str = '-'
        
        # P95 Latency (mean of valid reps)
        valid_lat = [r['p95_lat'] for r in valid_reps if r['p95_lat'] is not None]
        if valid_lat:
            lat_str = f"{sum(valid_lat)/len(valid_lat):.1f}"
        else:
            lat_str = '-'
        
        # Timeout rate (mean of all reps)
        all_timeout = [r['timeout_rate'] for r in rpm_rows if r['timeout_rate'] is not None]
        if all_timeout:
            timeout_str = f"{sum(all_timeout)/len(all_timeout)*100:.1f}"
        else:
            timeout_str = '-'
        
        # Prompt mix diff (mean of all reps)
        all_pm = [r['prompt_diff'] for r in rpm_rows if r['prompt_diff'] is not None]
        if all_pm:
            pm_str = f"{sum(all_pm)/len(all_pm):.0f}"
        else:
            pm_str = '-'
        
        # Dropped iterations (sum)
        dropped = sum(r['dropped'] for r in rpm_rows if r['dropped'])
        dropped_str = str(int(dropped)) if dropped > 0 else '0'
        
        # Status
        if len(valid_reps) == 3:
            status = r'\cellcolor{validgreen}Valid'
        elif len(valid_reps) > 0:
            status = r'\cellcolor{partialyellow}Partial'
        else:
            status = r'\cellcolor{invalidred}Invalid'
        
        latex.append(
            f"{i} & {rpm} & {valid_count} & {thr_str} & {lat_str} & "
            f"{timeout_str} & {pm_str} & {dropped_str} & {status} \\\\"
        )
    
    latex.extend([
        r"\bottomrule",
        r"\end{tabular}"
    ])
    
    output_file = OUTPUT_DIR / "table4_rag_performance.tex"
    with open(output_file, 'w') as f:
        f.write('\n'.join(latex))
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_decision_criteria_table():
    """Table 5: Decision Criteria Evaluation with row numbers."""
    
    criteria = [
        {
            'criterion': 'Validity Coverage',
            'rag': '10--20 RPM (2 points)',
            'n8n': '10--100 RPM (10 points)',
            'winner': 'n8n',
            'significant': 'Yes'
        },
        {
            'criterion': 'Timeout Rate',
            'rag': '0.0\\% (10--20 RPM)',
            'n8n': '0.0\\% (10--20 RPM)',
            'winner': 'Tie',
            'significant': 'No'
        },
        {
            'criterion': 'Error Rate',
            'rag': '0.0\\% (10--20 RPM)',
            'n8n': '$<$1\\% (10--20 RPM)',
            'winner': 'Comparable',
            'significant': 'No'
        },
        {
            'criterion': 'Throughput',
            'rag': '0.162--0.322 rps',
            'n8n': '0.160--0.297 rps',
            'winner': 'RAG',
            'significant': 'No'
        },
        {
            'criterion': 'P95 Latency',
            'rag': '39--42 s',
            'n8n': '52--200 s',
            'winner': 'RAG',
            'significant': 'Yes'
        },
        {
            'criterion': 'Scalability',
            'rag': 'Fails at $>$20 RPM',
            'n8n': 'Stable to 100 RPM',
            'winner': 'n8n',
            'significant': 'Yes'
        }
    ]
    
    latex = [
        r"\begin{tabular}{clccccl}",
        r"\toprule",
        r"\textbf{\#} & \textbf{Criterion} & \textbf{RAG} & \textbf{n8n} & \textbf{Winner} & \textbf{Significant} \\",
        r"\midrule"
    ]
    
    for i, crit in enumerate(criteria, 1):
        winner = crit['winner']
        if winner == 'n8n':
            winner_cell = r'\cellcolor{n8nwinner}n8n'
        elif winner == 'RAG':
            winner_cell = r'\cellcolor{ragwinner}RAG'
        elif winner == 'Tie':
            winner_cell = r'\cellcolor{tiecolor}Tie'
        else:
            winner_cell = r'\cellcolor{tiecolor}Comp.'
        
        latex.append(
            f"{i} & {crit['criterion']} & {crit['rag']} & {crit['n8n']} & "
            f"{winner_cell} & {crit['significant']} \\\\"
        )
    
    # Final decision row
    latex.append(r"\midrule")
    latex.append(
        r"\textbf{7} & \textbf{Final Decision} & \multicolumn{4}{c}{\cellcolor{finaldecision}\textbf{trade\_off\_not\_single\_winner}} \\"
    )
    
    latex.extend([
        r"\bottomrule",
        r"\end{tabular}"
    ])
    
    output_file = OUTPUT_DIR / "table5_decision_criteria.tex"
    with open(output_file, 'w') as f:
        f.write('\n'.join(latex))
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_preamble_packages():
    """Create preamble_packages.tex with required packages."""
    
    content = r"""% Required packages for benchmark tables
% Add these to your main.tex preamble if not already present

% For professional tables
\usepackage{booktabs}

% For cell coloring
\usepackage{xcolor}
\usepackage{colortbl}

% For advanced column formatting
\usepackage{array}

% Define colors for table cells
\definecolor{validgreen}{HTML}{D5F4E6}
\definecolor{invalidred}{HTML}{FADBD8}
\definecolor{partialyellow}{HTML}{FCF3CF}
\definecolor{n8nwinner}{HTML}{D4E6F1}
\definecolor{ragwinner}{HTML}{D5F4E6}
\definecolor{tiecolor}{HTML}{FCF3CF}
\definecolor{finaldecision}{HTML}{E8DAEF}

% For checkmarks and crosses
\usepackage{amssymb}

% For multi-row cells (if needed)
\usepackage{multirow}

% For proper number formatting
\usepackage{siunitx}
"""
    
    output_file = OUTPUT_DIR / "preamble_packages.tex"
    with open(output_file, 'w') as f:
        f.write(content)
    
    print(f"  Created: {output_file.name}")
    return output_file

def create_integration_guide():
    """Create INTEGRATION_GUIDE.md with usage examples."""
    
    content = """# LaTeX Table Integration Guide

## Quick Start

### 1. Add Required Packages

Add the following to your `main.tex` preamble (if not already present):

```latex
% Required packages for benchmark tables
\\usepackage{booktabs}      % Professional tables
\\usepackage{xcolor}        % Cell coloring
\\usepackage{colortbl}      % Table cell backgrounds
\\usepackage{array}         % Column formatting
\\usepackage{amssymb}       % Checkmarks and symbols

% Define colors
\\definecolor{validgreen}{HTML}{D5F4E6}
\\definecolor{invalidred}{HTML}{FADBD8}
\\definecolor{partialyellow}{HTML}{FCF3CF}
\\definecolor{n8nwinner}{HTML}{D4E6F1}
\\definecolor{ragwinner}{HTML}{D5F4E6}
\\definecolor{tiecolor}{HTML}{FCF3CF}
\\definecolor{finaldecision}{HTML}{E8DAEF}
```

Or simply input the preamble file:

```latex
\\input{preamble_packages}
```

### 2. Use Tables in Your Document

#### Table 1: Valid Comparison Summary (10-20 RPM)

```latex
\\begin{table}[htbp]
    \\centering
    \\caption{Valid comparison of n8n and RAG systems at 10--20 RPM with 
               individual repetition data and row numbers. All metrics 
               measured during 720s measurement window.}
    \\label{tab:valid-comparison-detailed}
    \\small
    \\input{table1_valid_comparison}
\\end{table}
```

#### Table 2a: n8n Validity Overview

```latex
\\begin{table}[htbp]
    \\centering
    \\caption{n8n system: Data quality and validity overview across all 
               RPM points (10--100). R1--R3 = repetitions. Point = all 3 
               repetitions valid.}
    \\label{tab:n8n-validity-overview}
    \\small
    \\input{table2a_n8n_validity}
\\end{table}
```

#### Table 2b: RAG Validity Overview

```latex
\\begin{table}[htbp]
    \\centering
    \\caption{RAG system: Data quality and validity overview across all 
               RPM points (10--100). R1--R3 = repetitions. Point = all 3 
               repetitions valid.}
    \\label{tab:rag-validity-overview}
    \\small
    \\input{table2b_rag_validity}
\\end{table}
```

#### Table 3: n8n Performance

```latex
\\begin{table}[htbp]
    \\centering
    \\caption{n8n system performance across full RPM range (10--100) with 
               row numbers and 95\\% confidence intervals.}
    \\label{tab:n8n-performance-full}
    \\small
    \\input{table3_n8n_performance}
\\end{table}
```

#### Table 4: RAG Performance

```latex
\\begin{table}[htbp]
    \\centering
    \\caption{RAG system performance and degradation from 10--100 RPM with 
               row numbers. Shows system failure progression.}
    \\label{tab:rag-performance-full}
    \\small
    \\input{table4_rag_performance}
\\end{table}
```

#### Table 5: Decision Criteria

```latex
\\begin{table}[htbp]
    \\centering
    \\caption{Preregistration decision criteria evaluation with row numbers.
               Significant indicates meaningful architectural differences.}
    \\label{tab:decision-criteria}
    \\input{table5_decision_criteria}
\\end{table}
```

## Row Numbers

All tables now include row numbers in the first column for easy reference:
- Table 1: Rows 1--12 (6 data rows per system)
- Table 2a: Rows 1--10 (RPM 10--100)
- Table 2b: Rows 1--10 (RPM 10--100)
- Table 3: Rows 1--10 (RPM 10--100)
- Table 4: Rows 1--10 (RPM 10--100)
- Table 5: Rows 1--7 (6 criteria + final decision)

Reference in text: `see row 5 in Table~\\ref{tab:n8n-performance-full}`

## Customization

### Font Size
If tables are too wide, use:
- `\\small` (recommended)
- `\\footnotesize` (smaller)

### Landscape Mode
For very wide tables, use:

```latex
\\begin{sidewaystable}
    \\centering
    \\caption{...}
    \\label{tab:...}
    \\input{table1_valid_comparison}
\\end{sidewaystable}
```

Requires: `\\usepackage{rotating}`

## Troubleshooting

### Missing Checkmarks
Ensure you have `\\usepackage{amssymb}` in your preamble.

### Cell Colors Not Working
Ensure both `xcolor` and `colortbl` are loaded.

### Row Numbers Not Showing
Check that the first column header is `\\\\textbf{\\\\#}`.
"""
    
    output_file = OUTPUT_DIR / "INTEGRATION_GUIDE.md"
    with open(output_file, 'w') as f:
        f.write(content)
    
    print(f"  Created: {output_file.name}")
    return output_file

def main():
    """Generate all LaTeX tables."""
    print("=" * 70)
    print("Generating LaTeX Tables from Benchmark Analysis")
    print("With Row Numbers and Split Validity Tables")
    print("=" * 70)
    print()
    
    print("Loading data files...")
    data = load_data()
    print(f"  Loaded {len(data)} data sources")
    print()
    
    print("Generating LaTeX tables...")
    print("-" * 50)
    
    create_valid_comparison_table(data)
    create_n8n_validity_table(data)
    create_rag_validity_table(data)
    create_n8n_performance_table(data)
    create_rag_performance_table(data)
    create_decision_criteria_table()
    create_preamble_packages()
    create_integration_guide()
    
    print("-" * 50)
    print()
    print("=" * 70)
    print(f"All files saved to: {OUTPUT_DIR}")
    print("=" * 70)
    print()
    print("Generated files:")
    for f in sorted(OUTPUT_DIR.glob("*.tex")):
        print(f"  \\\u251c\\u2500\\u2500 {f.name}")
    print()
    print("Next steps:")
    print("  1. Add packages from preamble_packages.tex to your main.tex")
    print("  2. Copy .tex files to your thesis directory")
    print("  3. Use \\\input{} to include tables (see INTEGRATION_GUIDE.md)")
    print()

if __name__ == "__main__":
    main()
