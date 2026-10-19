/* eslint-disable sonarjs/no-duplicate-string,no-magic-numbers */

const { ESLINT_STRICT, ORANGE_EVENT } = process.env;
const pipelineEvents = ['push', 'merge_request'];
const dynamicLevel = ESLINT_STRICT || !pipelineEvents.includes(ORANGE_EVENT) ? 'error' : 'warn';

module.exports = {
  root: true,
  ignorePatterns: ['node_modules/', '**/dist/'],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['sonarjs', 'import'],
  extends: ['plugin:sonarjs/recommended', 'eslint:recommended'],
  env: {
    browser: true,
    node: true,
    es6: true,
    commonjs: true,
    mocha: true,
  },
  globals: {
    globalThis: true,
    goog: true,
    Blockly: true,
    plug: 'readonly', // TSW module require
    seajs: 'readonly',
    mqq: true,
    $: true,
    mock: true,
    syncData: true,
  },
  rules: {
    complexity: ['error', 15],
    indent: ['error', 2, { SwitchCase: 1 }],
    'max-len': [
      'error',
      120,
      { ignoreStrings: true, ignoreTemplateLiterals: true, ignoreComments: true },
    ],
    'max-lines': ['error', { max: 400 }],
    'max-lines-per-function': ['error', { max: 80 }],
    'newline-before-return': ['error'],
    'padding-line-between-statements': [
      'error',
      { blankLine: 'always', prev: 'const', next: ['expression', 'block-like'] },
      { blankLine: 'always', prev: ['expression', 'block-like'], next: 'const' },
      { blankLine: 'never', prev: 'const', next: 'const' },
      { blankLine: 'always', prev: ['cjs-import', 'import'], next: '*' },
      { blankLine: 'any', prev: ['cjs-import', 'import'], next: ['cjs-import', 'import'] },
      { blankLine: 'always', prev: '*', next: 'multiline-const' },
      { blankLine: 'always', prev: 'multiline-const', next: '*' },
      { blankLine: 'always', prev: 'function', next: '*' },
      { blankLine: 'always', prev: '*', next: 'function' },
    ],
    'no-console': ['error'],
    'no-trailing-spaces': 'error',
    'no-constant-condition': ['error', { checkLoops: false }],
    'no-debugger': ['error'],
    'arrow-spacing': ['error'],
    'multiline-comment-style': ['error'],
    'no-magic-numbers': [
      'warn',
      { ignoreArrayIndexes: true, ignore: [-1, 0, 1, 2, 10, 24, 1000, 3600] },
    ],
    'no-multiple-empty-lines': ['error', { max: 1 }],
    'no-restricted-imports': [
      dynamicLevel,
      {
        patterns: [
          {
            group: ['../../**'],
            message: '不要使用过长的相对路径引用, 可以通过别称来明确引用模块在项目中的位置',
          },
        ],
      },
    ],
    'no-shadow-restricted-names': 'error',
    'lines-between-class-members': [
      'error',
      'always',
      {
        exceptAfterSingleLine: true,
      },
    ],
    'import/order': [
      dynamicLevel,
      {
        groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index', 'object'],
        pathGroups: [
          {
            pattern: '@*/**',
            group: 'internal',
            position: 'before',
          },
        ],
        pathGroupsExcludedImportTypes: [],
      },
    ],
    'no-multi-spaces': ['error', { ignoreEOLComments: true }],
    'object-curly-spacing': ['error', 'always'],
    'import/no-unresolved': 'off',
    'global-require': 'off',
    'import/prefer-default-export': 'off',
    'class-methods-use-this': 'off',
    eqeqeq: ['error', 'always'],
    'no-empty': dynamicLevel,
    'no-extra-semi': dynamicLevel,
    'no-empty-function': dynamicLevel,
    'sonarjs/no-nested-template-literals': dynamicLevel,
    'sonarjs/cognitive-complexity': [dynamicLevel, 10],
    'sonarjs/no-duplicate-string': dynamicLevel,
    'sonarjs/no-collapsible-if': dynamicLevel,
    'sonarjs/no-identical-functions': [dynamicLevel, 10],
    'sonarjs/no-same-line-conditional': dynamicLevel,
    'sonarjs/no-redundant-jump': dynamicLevel,
    'sonarjs/prefer-single-boolean-return': dynamicLevel,
    'sonarjs/prefer-object-literal': dynamicLevel,
    'sonarjs/no-duplicated-branches': dynamicLevel,
    'sonarjs/no-useless-catch': dynamicLevel,
    'sonarjs/no-ignored-return': dynamicLevel,
    'sonarjs/no-all-duplicated-branches': dynamicLevel,
    'sonarjs/no-gratuitous-expressions': dynamicLevel,
  },
  overrides: [
    // Existing orchestration functions need a separate structural refactor; keep reporting them.
    {
      files: ['apps/server/src/agent.ts', 'apps/web/src/App.vue'],
      rules: {
        'max-lines-per-function': ['warn', { max: 80 }],
        complexity: ['warn', 15],
        'sonarjs/cognitive-complexity': ['warn', 10],
      },
    },
    {
      files: ['*.js', '*.jsx', '*.mjs'],
      rules: {
        '@typescript-eslint/no-var-requires': 'off',
        '@typescript-eslint/explicit-function-return-type': 'off',
      },
      overrides: [
        {
          files: ['**/build/*.js'],
          rules: {
            'no-console': 'off',
          },
        },
      ],
    },
    {
      files: ['scripts/**/*.mjs'],
      rules: {
        'no-console': 'off',
        'no-magic-numbers': 'off',
      },
    },
    {
      files: ['*.spec.js', '*.test.ts'],
      rules: {
        'max-lines': 'off',
        'max-lines-per-function': 'off',
      },
    },
    {
      files: ['*.vue'],
      globals: {
        defineProps: true,
        defineEmits: true,
        defineExpose: true,
        withDefaults: true,
      },
      extends: ['plugin:vue/recommended', 'eslint:recommended'],
      parser: 'vue-eslint-parser',
      parserOptions: {
        parser: '@typescript-eslint/parser',
        extraFileExtensions: ['.vue'],
      },
      rules: {
        indent: 'off',
        'max-len': ['error', 120, { ignoreStrings: true, ignoreTemplateLiterals: true }],
        'max-lines': ['error', { max: 800 }],
        'no-unused-vars': [
          'error',
          // we are only using this rule to check for unused arguments since TS, catches unused variables but not args.
          { varsIgnorePattern: '.*', args: 'none' },
        ],
        'vue/no-multi-spaces': ['error'],
        'vue/no-spaces-around-equal-signs-in-attribute': ['error'],
        'vue/html-indent': ['error', 2],
        'vue/script-indent': ['error', 2],
        'vue/component-tags-order': [
          'error',
          {
            order: ['template', 'script', 'style'],
          },
        ],
        'vue/arrow-spacing': dynamicLevel,
        'vue/block-spacing': dynamicLevel,
        'vue/space-infix-ops': dynamicLevel,
        'vue/space-in-parens': dynamicLevel,
        'vue/array-bracket-spacing': dynamicLevel,
        'vue/object-curly-spacing': [dynamicLevel, 'always'],
        'vue/template-curly-spacing': dynamicLevel,
        'vue/no-child-content': [dynamicLevel],
        'vue/no-mutating-props': [dynamicLevel],
        'vue/no-reserved-props': [dynamicLevel],
        'vue/no-setup-props-destructure': [dynamicLevel],
        'vue/no-reserved-component-names': [dynamicLevel],
        'vue/multi-word-component-names': [dynamicLevel, { ignores: ['index'] }],
        'vue/component-name-in-template-casing': [dynamicLevel, 'kebab-case'],
        'vue/component-options-name-casing': [dynamicLevel, 'PascalCase'],
      },
    },
    {
      files: ['*.ts', '*.tsx'],
      parser: '@typescript-eslint/parser',
      parserOptions: { project: './tsconfig.eslint.json', tsconfigRootDir: __dirname },
      extends: [
        'plugin:@typescript-eslint/recommended',
        'plugin:@typescript-eslint/recommended-requiring-type-checking',
        'plugin:@typescript-eslint/strict',
      ],
      rules: {
        '@typescript-eslint/no-misused-promises': 'off',
        '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
        '@typescript-eslint/ban-ts-comment': 'warn',
        '@typescript-eslint/indent': ['error', 2],
        '@typescript-eslint/member-delimiter-style': ['error'],
        '@typescript-eslint/ban-types': ['error', { types: { Function: false } }],
        '@typescript-eslint/naming-convention': [
          dynamicLevel,
          {
            selector: 'parameter',
            format: ['camelCase'],
            leadingUnderscore: 'allow',
          },
          {
            selector: 'import',
            format: ['camelCase', 'PascalCase'],
          },
          {
            selector: 'default',
            format: ['camelCase'],
          },
          {
            selector: 'variable',
            modifiers: ['exported', 'const'],
            types: ['boolean', 'number', 'string'],
            format: ['UPPER_CASE'],
          },
          {
            selector: 'variable',
            format: ['camelCase'],
          },
          {
            selector: ['typeLike', 'enumMember'],
            format: ['PascalCase'],
          },
          {
            selector: 'objectLiteralProperty',
            format: null,
          },
        ],
        'lines-between-class-members': [
          'error',
          'always',
          {
            exceptAfterSingleLine: true,
          },
        ],
        '@typescript-eslint/no-floating-promises': [dynamicLevel, { ignoreVoid: true }],
        'no-unused-expressions': 'off',
        '@typescript-eslint/no-unused-expressions': 'error',
        '@typescript-eslint/prefer-optional-chain': dynamicLevel,
        '@typescript-eslint/no-unsafe-assignment': dynamicLevel,
        '@typescript-eslint/no-unsafe-member-access': dynamicLevel,
        '@typescript-eslint/no-unsafe-return': dynamicLevel,
        '@typescript-eslint/no-unsafe-argument': dynamicLevel,
        '@typescript-eslint/no-unsafe-call': dynamicLevel,
        '@typescript-eslint/restrict-template-expressions': dynamicLevel,
        '@typescript-eslint/restrict-plus-operands': dynamicLevel,
        '@typescript-eslint/require-await': dynamicLevel,
        '@typescript-eslint/unbound-method': dynamicLevel,
        '@typescript-eslint/await-thenable': dynamicLevel,
        '@typescript-eslint/no-unnecessary-type-assertion': dynamicLevel,
        '@typescript-eslint/no-dynamic-delete': dynamicLevel,
        '@typescript-eslint/no-explicit-any': dynamicLevel,
        '@typescript-eslint/no-extraneous-class': dynamicLevel,
        '@typescript-eslint/no-invalid-void-type': dynamicLevel,
        '@typescript-eslint/no-redundant-type-constituents': dynamicLevel,
        '@typescript-eslint/prefer-ts-expect-error': dynamicLevel,
        '@typescript-eslint/no-unsafe-enum-comparison': 'warn',
        '@typescript-eslint/no-non-null-assertion': 'warn',
        '@typescript-eslint/dot-notation': 'error',
      },
      overrides: [
        {
          files: ['*.d.ts'],
          rules: {
            '@typescript-eslint/naming-convention': 'off',
          },
        },
      ],
    },
  ],
};
