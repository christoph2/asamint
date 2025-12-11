/*
 * Auto-generated C header for calibration data.
 * Project: ${project}
 * Generator: ${generator}
 * NOTE: Types default to 'double' and 'char'; adjust as needed.
 */
#ifndef ${header_guard}
#define ${header_guard}

#include <stdint.h>

/* Individual categories */

% if arrays_by_cat.get('AXIS_PTS'):
typedef struct {
% for a in arrays_by_cat['AXIS_PTS']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}[${'']['.join(str(d) for d in a.dims).replace('][', '][')}];
% endfor
} AXIS_PTS_t;
% endif

% if arrays_by_cat.get('CURVE'):
typedef struct {
% for a in arrays_by_cat['CURVE']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}[${'']['.join(str(d) for d in a.dims).replace('][', '][')}];
% endfor
} CURVE_t;
% endif

% if arrays_by_cat.get('MAP'):
typedef struct {
% for a in arrays_by_cat['MAP']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}% if len(a.dims) == 1 %
[${a.dims[0]}]
% else %
[${a.dims[0]}][${a.dims[1]}]
% endif %;
% endfor
} MAP_t;
% endif

% if arrays_by_cat.get('CUBOID'):
typedef struct {
% for a in arrays_by_cat['CUBOID']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}[${'']['.join(str(d) for d in a.dims).replace('][', '][')}];
% endfor
} CUBOID_t;
% endif

% if arrays_by_cat.get('CUBE_4'):
typedef struct {
% for a in arrays_by_cat['CUBE_4']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}[${'']['.join(str(d) for d in a.dims).replace('][', '][')}];
% endfor
} CUBE_4_t;
% endif

% if arrays_by_cat.get('CUBE_5'):
typedef struct {
% for a in arrays_by_cat['CUBE_5']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}[${'']['.join(str(d) for d in a.dims).replace('][', '][')}];
% endfor
} CUBE_5_t;
% endif

% if arrays_by_cat.get('VAL_BLK'):
typedef struct {
% for a in arrays_by_cat['VAL_BLK']:
    /* ${a.name}${' - ' + a.comment if a.comment else ''} */
    ${a.c_type} ${a.c_name}[${'']['.join(str(d) for d in a.dims).replace('][', '][')}];
% endfor
} VAL_BLK_t;
% endif

% if values:
typedef struct {
% for v in values:
    /* ${v.name}${' - ' + v.comment if v.comment else ''} */
    ${v.c_type} ${v.c_name};
% endfor
} VALUE_t;
% endif

% if asciis:
typedef struct {
% for s in asciis:
    /* ${s.name}${' - ' + s.comment if s.comment else ''} */
    char ${s.c_name}[${s.length + 1}];
% endfor
} ASCII_t;
% endif

/* Master struct aggregating categories */
typedef struct {
% if arrays_by_cat.get('AXIS_PTS'):
    AXIS_PTS_t axis_pts;
% endif
% if arrays_by_cat.get('CURVE'):
    CURVE_t curves;
% endif
% if arrays_by_cat.get('MAP'):
    MAP_t maps;
% endif
% if arrays_by_cat.get('CUBOID'):
    CUBOID_t cuboids;
% endif
% if arrays_by_cat.get('CUBE_4'):
    CUBE_4_t cube4;
% endif
% if arrays_by_cat.get('CUBE_5'):
    CUBE_5_t cube5;
% endif
% if arrays_by_cat.get('VAL_BLK'):
    VAL_BLK_t val_blks;
% endif
% if values:
    VALUE_t values;
% endif
% if asciis:
    ASCII_t asciis;
% endif
} Calibration_t;

#endif /* ${header_guard} */
