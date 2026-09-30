### 표

| Drug Features       | Indication Features | Sponsor Features           | Trial Features           |
|---------------------|---------------------|----------------------------|--------------------------|
| Drug classification | Therapeutic area    | Entity type                | Phase                    |
| Compound type       | Disease subgroup    | Headquarters location      | Status                   |
| Biological target   | Prevalence          | Number of approvals        | Site locations           |
| Mechanism of action | Incidence           | Therapeutic area track record | Actual-to-target accrual ratio |
| Prior approvals     | Prior approvals     | Phase success track record | Intervention model       |

*Figure 12: Sample of the 200-plus features extracted from Pharmaprojects, Trialtrove, and Biomedtracker.*

---

### 다이어그램 (Figure 13: Decision Tree)

- Big Pharma? → Yes → Double-Blind? → Yes → Biologic? → Yes → 64%
- Big Pharma? → Yes → Double-Blind? → Yes → Biologic? → No → 52%
- Big Pharma? → Yes → Double-Blind? → No → Fast Track? → Yes → 70%
- Big Pharma? → Yes → Double-Blind? → No → Fast Track? → No → 55%
- Big Pharma? → No → Small Molecule? → Yes → Prior Approval? → Yes → 67%
- Big Pharma? → No → Small Molecule? → Yes → Prior Approval? → No → 49%
- Big Pharma? → No → Small Molecule? → No → Lead Indication? → Yes → 58%
- Big Pharma? → No → Small Molecule? → No → Lead Indication? → No → 54%

*Figure 13: A hypothetical representation of a single, simplified decision tree. The percentages at the “leaves” of the tree denote the fraction of training data samples that are categorized by a given pathway.*

---

### 이미지 속 글자

- Part 2. Predictive Analysis of Clinical Success
- Sample of the 200-plus features driving success rate probabilities
- Big Pharma?
- Double-Blind?
- Biologic?
- Fast Track?
- Small Molecule?
- Prior Approval?
- Lead Indication?
- 64%, 52%, 70%, 55%, 67%, 49%, 58%, 54%
- Figure 12: Sample of the 200-plus features extracted from Pharmaprojects, Trialtrove, and Biomedtracker.
- Figure 13: A hypothetical representation of a single, simplified decision tree. The percentages at the “leaves” of the tree denote the fraction of training data samples that are categorized by a given pathway.
- 19 / February 2021
- © BIO | QLS Advisors | Informa UK Ltd 2021 (Unauthorized photocopying prohibited.)