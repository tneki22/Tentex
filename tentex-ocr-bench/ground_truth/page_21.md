---
source: LaTeX-компиляция Tectonic
page_number: 3
modality: native_pdf
text_layer: true
images: 0
---

# Нативный PDF: вероятность и статистика

Для дискретной случайной величины $X$ математическое ожидание и дисперсия равны

$$\mathbb{E}X = \sum_k x_k p_k, \tag{N.10}$$

$$\operatorname{Var}(X) = \mathbb{E}\bigl[(X-\mathbb{E}X)^2\bigr] =\mathbb{E}X^2-(\mathbb{E}X)^2. \tag{N.11}$$

Плотность нормального распределения:

$$p(x)=\frac{1}{\sigma\sqrt{2\pi}}\exp\!\left[-\frac{(x-\mu)^2}{2\sigma^2}\right]. \tag{N.12}$$

Формула Байеса для полной группы гипотез $H_1,\ldots,H_m$:

$$\mathbb{P}(H_i\mid A)=\frac{\mathbb{P}(H_i)\,\mathbb{P}(A\mid H_i)}{\sum_{j=1}^{m}\mathbb{P}(H_j)\,\mathbb{P}(A\mid H_j)}. \tag{N.13}$$

В качестве теста комбинаторной записи используем биномиальное тождество

$$\sum_{k=0}^{n}\binom{n}{k}p^k(1-p)^{n-k}=1. \tag{N.14}$$
