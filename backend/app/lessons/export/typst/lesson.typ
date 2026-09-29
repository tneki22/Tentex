// Оформление PDF уроков Tentex. `main.typ` собирает `render_typst.py`,
// формулы рисует `formulas.typ` в SVG, а `formulas.json` связывает их с текстом.

#let ink = rgb("#1f2328")
#let quiet = rgb("#6b7280")
#let hairline = rgb("#d6d9de")
#let accents = (
  important: rgb("#b45309"),
  example: rgb("#15803d"),
  definition: rgb("#1d4ed8"),
  warning: rgb("#b91c1c"),
)
#let invisible = rgb(0, 0, 0, 0)

// Размеры формул записаны при 11pt, поэтому формула меряется в em и растёт
// вместе с текстом заголовка и мельчает в подписи.
#let formula-size = 11
#let formulas = json("formulas.json")

// Невидимый LaTeX поверх нарисованной формулы: текстовый слой PDF отдаёт
// `$\frac{a}{b}$`, и скопированное вставляется в пояснение урока как формула.
#let latex-layer(src, w, h) = context {
  let line = text(font: "DejaVu Sans Mono", size: 8pt, fill: invisible, hyphenate: false, src)
  let size = measure(line)
  // Строка не должна переноситься по ширине формулы: иначе в текстовом слое
  // исходник рвётся на куски. Коробка в свою ширину, затем сжатие до формулы.
  let body = box(width: size.width, height: size.height, line)
  let sx = if size.width > 0pt { w.to-absolute() / size.width * 100% } else { 100% }
  let sy = if size.height > 0pt { h.to-absolute() / size.height * 100% } else { 100% }
  scale(x: sx, y: sy, origin: top + left, reflow: false, body)
}

#let fx(key) = {
  let f = formulas.at(key)
  if f.file == none {
    // mitex не разобрал формулу — показываем исходник, он и есть текстовый слой.
    return text(fill: quiet, raw(f.src))
  }
  let w = f.w / formula-size * 1em
  let h = f.h / formula-size * 1em
  let body = box(width: w, height: h, {
    image(f.file, width: w, height: h)
    place(top + left, latex-layer(f.src, w, h))
  })
  if f.display {
    block(width: 100%, above: 0.9em, below: 0.9em, align(center, layout(size => {
      let limit = size.width
      let actual = measure(body).width
      if actual > limit { scale(limit / actual * 100%, reflow: true, body) } else { body }
    })))
  } else {
    box(baseline: (f.h - f.b) / formula-size * 1em, body)
  }
}

#let muted(body) = text(size: 0.86em, fill: quiet, body)

#let cite-mark(label) = text(size: 0.8em, fill: quiet, baseline: -0.3em, "[" + label + "]")

#let callout(kind, title, body) = block(
  width: 100%,
  inset: (left: 10pt, rest: 8pt),
  stroke: (left: 2.5pt + accents.at(kind, default: quiet)),
  fill: accents.at(kind, default: quiet).lighten(94%),
  radius: (right: 3pt),
  breakable: true,
  {
    // Заголовок блока не остаётся один внизу страницы: он липнет к тексту.
    block(sticky: true, below: 0.6em, text(weight: "bold", fill: accents.at(kind, default: quiet), title))
    body
  },
)

#let source-box(title, note: none, body) = block(
  width: 100%,
  inset: (left: 10pt, rest: 8pt),
  stroke: (left: 1.5pt + hairline),
  breakable: true,
  {
    block(sticky: true, below: 0.6em, {
      text(size: 0.82em, fill: quiet, style: "italic", "Из материала: " + title)
      if note != none {
        linebreak()
        text(size: 0.82em, fill: accents.warning, note)
      }
    })
    body
  },
)

#let task-box(number, label, body) = block(
  width: 100%,
  inset: 9pt,
  stroke: 0.6pt + hairline,
  radius: 3pt,
  breakable: true,
  {
    block(sticky: true, below: 0.6em, {
      text(weight: "bold", "Задание " + str(number) + ". ")
      text(fill: quiet, style: "italic", label)
    })
    body
  },
)

#let answer(number, body) = block(width: 100%, breakable: true, grid(
  columns: (1.8em, 1fr),
  column-gutter: 0.3em,
  text(weight: "bold", str(number) + "."),
  body,
))

#let picture(file, width: none, caption: none) = block(width: 100%, breakable: false, {
  align(center, if width == none {
    // Картинка в свой размер, но не шире строки.
    layout(size => {
      let img = image(file)
      let actual = measure(img).width
      if actual > size.width { image(file, width: 100%) } else { img }
    })
  } else {
    image(file, width: width * 100%)
  })
  if caption != none {
    align(center, muted(caption))
  }
})

#let lesson-doc(title: "", lessons: 1, body) = {
  set document(title: title)
  set page(
    paper: "a4",
    margin: (x: 2.2cm, top: 2cm, bottom: 2.2cm),
    footer: context align(center, text(size: 8.5pt, fill: quiet, counter(page).display())),
  )
  set text(font: "New Computer Modern", size: 11pt, lang: "ru", fill: ink)
  set par(justify: true, leading: 0.62em, spacing: 0.9em)
  set heading(numbering: none)
  show heading.where(level: 1): it => {
    pagebreak(weak: true)
    block(below: 0.4em, text(size: 1.55em, weight: "bold", it.body))
  }
  show heading.where(level: 2): set text(size: 1.2em)
  show heading.where(level: 3): set text(size: 1.08em)
  show heading: set block(above: 1.3em, below: 0.7em)
  show heading: set text(hyphenate: false)
  show heading: set par(justify: false)
  show link: set text(fill: accents.definition)
  show raw.where(block: true): it => block(
    width: 100%, inset: 8pt, fill: rgb("#f5f6f8"), radius: 3pt, text(size: 0.88em, it),
  )
  set table(stroke: 0.5pt + hairline, inset: 6pt)
  show table.cell.where(y: 0): set text(weight: "bold")
  set quote(block: true)
  show quote: set block(inset: (left: 10pt), stroke: (left: 1.5pt + hairline))
  if lessons > 1 {
    align(center + horizon, {
      text(size: 2em, weight: "bold", title)
      v(1.5em)
      text(fill: quiet, "Уроков: " + str(lessons))
    })
    pagebreak()
    outline(title: "Содержание", depth: 1)
  }
  body
}

#let lesson-head(goal: none, topics: none) = {
  if topics != none { muted("Темы: " + topics); parbreak() }
  if goal != none { text(style: "italic", "Цель: " + goal); parbreak() }
  line(length: 100%, stroke: 0.5pt + hairline)
}
