import { Crepe } from "@milkdown/crepe";

/**
 * Русские подписи для Crepe: без этого редактор говорит по-английски
 * («Please enter…», «Upload», «Confirm»…) — пакетных RU-переводов у Crepe нет,
 * поэтому строки заданы явно. Общий модуль для «Моего конспекта» и «Сводного
 * конспекта»: описание пунктов меню и подсказок должно звучать одинаково.
 */
export const CONSPECT_FEATURE_TEXT = {
  [Crepe.Feature.Placeholder]: {
    text: "Начните писать конспект…",
  },
  [Crepe.Feature.ImageBlock]: {
    inlineUploadButton: "Загрузить",
    inlineUploadPlaceholderText: "или вставьте ссылку",
    inlineConfirmButton: "Подтвердить",
    blockUploadButton: "Загрузить изображение",
    blockConfirmButton: "Подтвердить",
    blockCaptionPlaceholderText: "Подпись изображения",
    blockUploadPlaceholderText: "или перетащите файл сюда",
  },
  [Crepe.Feature.LinkTooltip]: {
    editButton: "Изменить",
    removeButton: "Удалить",
    confirmButton: "Подтвердить",
    inputPlaceholder: "Вставьте ссылку",
  },
  [Crepe.Feature.Toolbar]: {
    boldLabel: "Жирный",
    codeLabel: "Код",
    italicLabel: "Курсив",
    linkLabel: "Ссылка",
    strikethroughLabel: "Зачёркнутый",
    latexLabel: "Формула",
  },
  [Crepe.Feature.Latex]: {
    katexOptions: { throwOnError: false },
    inlineEditConfirm: "Подтвердить",
  },
  [Crepe.Feature.CodeMirror]: {
    previewToggleText: (previewOnlyMode: boolean) => (previewOnlyMode ? "Редактировать" : "Просмотр"),
    previewLabel: "Просмотр",
    searchPlaceholder: "Найти язык",
    noResultText: "Ничего не найдено",
    copyText: "Скопировать",
  },
  [Crepe.Feature.BlockEdit]: {
    textGroup: {
      label: "Текст",
      text: { label: "Текст" },
      h1: { label: "Заголовок 1" },
      h2: { label: "Заголовок 2" },
      h3: { label: "Заголовок 3" },
      h4: { label: "Заголовок 4" },
      h5: { label: "Заголовок 5" },
      h6: { label: "Заголовок 6" },
      quote: { label: "Цитата" },
      divider: { label: "Разделитель" },
    },
    listGroup: {
      label: "Список",
      bulletList: { label: "Маркированный список" },
      orderedList: { label: "Нумерованный список" },
      taskList: { label: "Список задач" },
    },
    advancedGroup: {
      label: "Вставка",
      image: { label: "Изображение" },
      codeBlock: { label: "Блок кода" },
      table: { label: "Таблица" },
      math: { label: "Формула" },
    },
  },
};
