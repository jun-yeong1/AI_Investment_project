Example of probability decomposition (그래프)

- 제목: Example of probability decomposition
- 범례: Increase (빨강), Decrease (회색), Total (분홍)
- Y축: 0.0% ~ 100.0% (10% 단위)
- X축 라벨 및 값:
  - Baseline POA: 35.0% (Total, 분홍)
  - Breakthrough Therapy: +20.6% (Increase, 빨강)
  - Positive Trial Outcome: +12.8% (Increase, 빨강)
  - Target is PARP: +4.6% (Increase, 빨강)
  - Drug has Prior Approval: +3.6% (Increase, 빨강)
  - Tumor Type is Solid: -2.0% (Decrease, 회색)
  - All Other Features: -2.8% (Decrease, 회색)
  - QLS POA: 71.8% (Total, 분홍)

이미지 속 글자:
- Feature Importance
- Given the stakes involved in the drug development process, machine learning forecasts must not only be accurate, but also interpretable to stakeholders charged with the responsibility of making go/no-go decisions. These decision-makers need to understand why a given forecast differs from the historical average, and which features were most important in driving the difference or delta with respect to the disease-group baseline LOA. To increase the transparency of our forecasts, the QLS machine learning algorithm reports the most important features and their individual contributions to the forecast’s delta.
- As an illustration, we decompose our probability of approval (POA) prediction of an oncology drug that is currently in phase 3 clinical trials into its key components. (Note that we use the term POA for the QLS machine-learning forecasts to differentiate from the empirical “LOA” presented in Part I.) Figure 14 reports the top five features that increase this program’s estimated probability of approval from its therapeutic area historical baseline of 35.0% from phase 3 to approval, to 71.8%. The top positive feature driving this higher than average probability is its breakthrough therapy designation (+20.6%). This designation is granted when the FDA has determined that preliminary clinical evidence indicates that the drug may demonstrate substantial clinical improvement over available therapies. Further positive clinical evidence in phase 2 increases the estimate by an additional +6.4%. Next, because it is a PARP inhibitor (+4.6%) that has been previously approved for another indication (+3.6%), the POA is augmented by an additional 8.2%. Finally, its treatment of a solid tumor type (-2.0%) and the net aggregate contribution of other features (-2.8%) penalize the overall POA score slightly.
- Figure 14: Decomposition of the probability of approval estimate for an anti-cancer drug that is currently in phase 3 clinical trials for prostate cancer. The top five features that increase this program’s estimated probability of approval from the historical phase 3 to approval baseline in oncology of 35.0% to 71.8% are reported.
- Abbreviations: POA=probability of approval; PARP= poly ADP-ribose polymerase.

페이지 하단:
- 20/ February 2021
- © BIO | QLS Advisors | Informa UK Ltd 2021 (Unauthorized photocopying prohibited.)