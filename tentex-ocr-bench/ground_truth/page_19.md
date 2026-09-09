---
source: LaTeX-компиляция Tectonic
page_number: 1
modality: native_pdf
text_layer: true
images: 0
---

# Нативный PDF: формулы математического анализа

*Формулы набраны LaTeX и не растеризованы*

Пусть $f$ непрерывна на отрезке $[a,b]$, а $F'(x)=f(x)$. Тогда формула Ньютона--Лейбница имеет вид

$$\int_a^b f(x)\,dx = F(b)-F(a). \tag{N.1}$$

Для функции двух переменных полный дифференциал и квадратичная форма второго порядка записываются так:

$$du = \frac{\partial u}{\partial x}\,dx + \frac{\partial u}{\partial y}\,dy, \tag{N.2}$$

$$d^2u = u_{xx}\,dx^2 + 2u_{xy}\,dx\,dy + u_{yy}\,dy^2. \tag{N.3}$$

Ряд Фурье функции периода $2\pi$ задаётся формулой

$$f(x) \sim \frac{a_0}{2}+\sum_{n=1}^{\infty}\bigl(a_n\cos nx+b_n\sin nx\bigr), \quad a_n=\frac{1}{\pi}\int_{-\pi}^{\pi}f(x)\cos nx\,dx. \tag{N.4}$$

Для проверки распознавания пределов включим составную дробь:

$$\lim_{x\to0}\frac{\sqrt{1+x}-1}{x}=\frac12, \qquad \lim_{n\to\infty}\left(1+\frac{x}{n}\right)^n=e^x. \tag{N.5}$$
