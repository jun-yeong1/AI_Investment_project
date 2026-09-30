### 그래프: Feature importance by phase to approval

- 제목: Feature importance by phase to approval
- 축 이름:
  - 세로축: Feature Importance (%)
  - 가로축: 변수명
- 단위: %

| 변수명                  | Phase I to Approval | Phase II to Approval | Phase III to Approval | NDA/BLA |
|-------------------------|---------------------|----------------------|-----------------------|---------|
| Indication              | 약 33%              | 약 29%               | 약 26%                | 약 38%  |
| Biological Target       | 약 16%              | 약 14%               | 약 10%                | 약 10%  |
| Drug Modality           | 약 10%              | 약 11%               | 약 11%                | 약 10%  |
| Lead Indication         | 약 9%               | 약 11%               | 약 10%                | 약 5%   |
| Drug has Prior Approval | 약 8%               | 약 7%                | 약 3%                 | 약 3%   |
| Fast Track              | 약 6%               | 약 5%                | 약 4%                 | 약 4%   |
| Sponsor has Prior Success| 약 4%               | 약 6%                | 약 5%                 | 약 2%   |
| Trial Outcome           | 약 5%               | 약 6%                | 약 24%                | 약 22%  |
| Orphan Drug Designation | 약 3%               | 약 3%                | 약 2%                 | 약 2%   |
| Preselection Biomarker  | 약 1%               | 약 2%                | 약 3%                 | 약 2%   |
| Breakthrough Therapy    | 약 0%               | 약 6%                | 약 0%                 | 약 2%   |

---

### 이미지 속 글자

- "Although each individual prediction may have unique drivers, we can also extract the most informative variables across all predictions to gain insight into some of the most common predictors of success. Figure 15 summarizes our results."
- "Feature importance by phase to approval"
- "Phase I to Approval" (분홍색)
- "Phase II to Approval" (회색)
- "Phase III to Approval" (연분홍색)
- "NDA/BLA" (보라색)
- "Figure 15: The most important features of our random forest classifier across all predictions. Feature importance is normalized to sum to 100%. Note that individual predictions may have unique drivers specific to a given therapeutic area, trial design, or drug profile that are not listed here. Source: QLS Advisors."
- "The indication was consistently ranked the top variable across all clinical development phases. Indeed, success rates vary substantially across indications even within a therapeutic area. For example, in oncology, the overall phase 1 to approval LOA ranges from a minimum of 1.1% (n=275) for pancreatic cancer to a maximum of 15.2% (n=33) for alimentary cancers. We also observe that lead indication status, prior approval of a drug for another indication, and biological target validation all have a significant impact on the probability of approval. In some cases, developing an already approved drug for a new indication—one that has a controlled manufacturing process, and has already been shown to be safe in humans—has a greater likelihood of success than a novel indication. In other cases, the success rates for lead indications may be higher if a sponsor initiates clinical trials for multiple follow-on indications for which the drug was not originally intended, and many of the initiated clinical trials for the same drug fail."
- "Analysis showed that the trial outcome (whether the trial was completed, with its primary endpoints met) has significant associations with late-stage clinical success. It is easy to imagine that a drug-indication pair whose trial failed to meet its endpoints has a low probability of success in advancing to approval. For example, as of December 31, 2020, our algorithm predicts that one specific BLA for Alzheimer’s disease has only a 65% chance of progressing from regulatory review to approval, even though historically 83% of neurology drugs have made the transition to approval once they have reached this stage. The observation that the biologic failed to meet its primary endpoints in phase 3 is the top contributor (-15%) to this adjustment from the"

---

표, 다이어그램, 기타 차트는 없음.