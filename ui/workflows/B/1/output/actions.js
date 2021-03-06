/* This section is visually separate, but belongs to the parameters state */
export const setOutPath = path => ({
  type: 'PARAMETERS.SET_OUT_PATH',
  data: path,
})

export const setOutFormat = format => ({
  type: 'PARAMETERS.SET_OUT_FORMAT',
  data: format,
})
