# Сторонние библиотеки прототипа

Лежат в проекте, а не берутся из интернета: сайт работает с ноутбука-сервера и с телефона без внешних адресов.

## TipTap 3.30.0 — редактор «Рабочих заметок» (MIT)

`tiptap-3.30.0.min.js` — один файл, `window.Tiptap` (что в нём — `tiptap-entry.js`). Собрать заново:

```sh
mkdir /tmp/tt && cd /tmp/tt && echo '{"private":true}' > package.json
V=3.30.0; npm install --save-exact @tiptap/core@$V @tiptap/pm@$V @tiptap/starter-kit@$V @tiptap/extension-list@$V \
  @tiptap/extensions@$V @tiptap/extension-table@$V @tiptap/extension-image@$V @tiptap/suggestion@$V esbuild@0.25.10
cp <репозиторий>/Design/prototype/vendor/tiptap-entry.js entry.js
./node_modules/.bin/esbuild entry.js --bundle --minify --format=iife --global-name=Tiptap --target=es2018 \
  --legal-comments=eof --outfile=tiptap-3.30.0.min.js
```
