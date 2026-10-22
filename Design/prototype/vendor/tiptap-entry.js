// Сборка TipTap для «Рабочих заметок»: один файл, window.Tiptap
export { Editor, Node, Extension, mergeAttributes, wrappingInputRule } from '@tiptap/core';
export { default as StarterKit } from '@tiptap/starter-kit';
export { TaskList, TaskItem } from '@tiptap/extension-list';
export { Placeholder } from '@tiptap/extensions';
export { TableKit } from '@tiptap/extension-table';
export { default as Image } from '@tiptap/extension-image';
export { default as Suggestion } from '@tiptap/suggestion';
export { PluginKey, Plugin } from '@tiptap/pm/state';
