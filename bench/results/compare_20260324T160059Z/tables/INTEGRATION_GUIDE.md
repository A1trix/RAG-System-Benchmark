# LaTeX Table Integration Guide

## Quick Start

### 1. Add Required Packages

Add the following to your `main.tex` preamble (if not already present):

```latex
% Required packages for benchmark tables
\usepackage{booktabs}      % Professional tables
\usepackage{xcolor}        % Cell coloring
\usepackage{colortbl}      % Table cell backgrounds
\usepackage{array}         % Column formatting
\usepackage{amssymb}       % Checkmarks and symbols

% Define colors
\definecolor{validgreen}{HTML}{D5F4E6}
\definecolor{invalidred}{HTML}{FADBD8}
\definecolor{partialyellow}{HTML}{FCF3CF}
\definecolor{n8nwinner}{HTML}{D4E6F1}
\definecolor{ragwinner}{HTML}{D5F4E6}
\definecolor{tiecolor}{HTML}{FCF3CF}
\definecolor{finaldecision}{HTML}{E8DAEF}
```

Or simply input the preamble file:

```latex
\input{preamble_packages}
```

### 2. Use Tables in Your Document

#### Table 1: Valid Comparison Summary (10-20 RPM)

```latex
\begin{table}[htbp]
    \centering
    \caption{Valid comparison of n8n and RAG systems at 10--20 RPM with 
               individual repetition data and row numbers. All metrics 
               measured during 720s measurement window.}
    \label{tab:valid-comparison-detailed}
    \small
    \input{table1_valid_comparison}
\end{table}
```

#### Table 2a: n8n Validity Overview

```latex
\begin{table}[htbp]
    \centering
    \caption{n8n system: Data quality and validity overview across all 
               RPM points (10--100). R1--R3 = repetitions. Point = all 3 
               repetitions valid.}
    \label{tab:n8n-validity-overview}
    \small
    \input{table2a_n8n_validity}
\end{table}
```

#### Table 2b: RAG Validity Overview

```latex
\begin{table}[htbp]
    \centering
    \caption{RAG system: Data quality and validity overview across all 
               RPM points (10--100). R1--R3 = repetitions. Point = all 3 
               repetitions valid.}
    \label{tab:rag-validity-overview}
    \small
    \input{table2b_rag_validity}
\end{table}
```

#### Table 3: n8n Performance

```latex
\begin{table}[htbp]
    \centering
    \caption{n8n system performance across full RPM range (10--100) with 
               row numbers and 95\% confidence intervals.}
    \label{tab:n8n-performance-full}
    \small
    \input{table3_n8n_performance}
\end{table}
```

#### Table 4: RAG Performance

```latex
\begin{table}[htbp]
    \centering
    \caption{RAG system performance and degradation from 10--100 RPM with 
               row numbers. Shows system failure progression.}
    \label{tab:rag-performance-full}
    \small
    \input{table4_rag_performance}
\end{table}
```

#### Table 5: Decision Criteria

```latex
\begin{table}[htbp]
    \centering
    \caption{Preregistration decision criteria evaluation with row numbers.
               Significant indicates meaningful architectural differences.}
    \label{tab:decision-criteria}
    \input{table5_decision_criteria}
\end{table}
```

## Row Numbers

All tables now include row numbers in the first column for easy reference:
- Table 1: Rows 1--12 (6 data rows per system)
- Table 2a: Rows 1--10 (RPM 10--100)
- Table 2b: Rows 1--10 (RPM 10--100)
- Table 3: Rows 1--10 (RPM 10--100)
- Table 4: Rows 1--10 (RPM 10--100)
- Table 5: Rows 1--7 (6 criteria + final decision)

Reference in text: `see row 5 in Table~\ref{tab:n8n-performance-full}`

## Customization

### Font Size
If tables are too wide, use:
- `\small` (recommended)
- `\footnotesize` (smaller)

### Landscape Mode
For very wide tables, use:

```latex
\begin{sidewaystable}
    \centering
    \caption{...}
    \label{tab:...}
    \input{table1_valid_comparison}
\end{sidewaystable}
```

Requires: `\usepackage{rotating}`

## Troubleshooting

### Missing Checkmarks
Ensure you have `\usepackage{amssymb}` in your preamble.

### Cell Colors Not Working
Ensure both `xcolor` and `colortbl` are loaded.

### Row Numbers Not Showing
Check that the first column header is `\\textbf{\\#}`.
