---
source: LaTeX-компиляция Tectonic
page_number: 2
modality: native_pdf
text_layer: true
images: 0
---

# Нативный PDF: линейная алгебра и системы

Система линейных уравнений $A\mathbf{x}=\mathbf{b}$ имеет единственное решение, если $\det A\ne0$. В развёрнутом виде:

$$\begin{cases}2x-y+3z=7,\\x+4y-z=2,\\3x+2y+2z=9.\end{cases} \tag{N.6}$$

Определитель и обратная матрица:

$$\det A=\sum_{\sigma\in S_n}\operatorname{sgn}(\sigma)\prod_{i=1}^{n}a_{i,\sigma(i)}, \qquad A^{-1}=\frac{1}{\det A}\operatorname{adj}A. \tag{N.7}$$

Спектральное разложение симметрической матрицы:

$$A=Q\Lambda Q^{\mathsf T},\qquad Q^{\mathsf T}Q=I, \qquad \Lambda=\operatorname{diag}(\lambda_1,\ldots,\lambda_n). \tag{N.8}$$

Норма и скалярное произведение:

$$\|\mathbf{x}\|_2=\sqrt{\sum_{i=1}^{n}|x_i|^2}, \qquad \langle\mathbf{x},\mathbf{y}\rangle=\mathbf{x}^{\mathsf T}\mathbf{y}. \tag{N.9}$$
