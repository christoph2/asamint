
/*
    pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2009-2020 by Christoph Schueler <cpu12.gems@googlemail.com>

   All Rights Reserved

  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 2 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License along
  with this program; if not, write to the Free Software Foundation, Inc.,
  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
*/

//
//  Requires ANTLR >= 4.5.1 !!!
//

/*
** Grammar based on ANTLR4 example.
*/

grammar dcm20;

konservierung:
   (
   // ('\n')* 'KONSERVIERUNG_FORMAT' version=FLOAT /*'2.0'*/ ('\n')+
   version = file_format
   kopf = kons_kopf
   rumpf = kons_rumpf
   )?   // Consider empty filez.
   ;

file_format:
    ('\n')*
    ('KONSERVIERUNG_FORMAT' version=FLOAT /*'2.0'*/ ('\n')+)?
    ;

kons_kopf:
   (info = modulkopf_info)? (func_def = funktionsdef)? (var_def = variantendef)?
   ;

modulkopf_info:
   (m += mod_zeile)+
   ;

mod_zeile:
   anf = mod_anf_zeile (fort += mod_fort_zeile)*
   ;

mod_anf_zeile:
   'MODULKOPF' n = mod_ele_name w = mod_ele_wert
   ;

mod_fort_zeile:
   'MODULKOPF' w = mod_ele_wert
   ;

mod_ele_name:
   n = nameValue
   ;

mod_ele_wert:
   t = textValue ('\n')+
   ;

funktionsdef:
   'FUNKTIONEN' '\n' (f += funktionszeile)+ 'END' ('\n')+
   ;

funktionszeile:
   'FKT' n = nameValue v = fkt_version l = fkt_langname
   ;

fkt_version:
   t = textValue
   ;

fkt_langname:
   t = textValue ('\n')+
   ;

variantendef:
   'VARIANTENKODIERUNG' '\n' (v += variantenkrit)+ 'END' ('\n')+
   ;

variantenkrit:
   'KRITERIUM' n = krit_name (w += krit_wert)* ('\n')+
   ;

krit_name:
   n = nameValue
   ;

krit_wert:
   n = nameValue
   ;

kons_rumpf:
   (k += kenngroesse)*
   ;

kenngroesse:
   (
        kw = kennwert
      | kwb = kennwerteblock
      | kl = kennlinie
      | kf = kennfeld
      | gst = gruppenstuetzstellen
      | kt = kenntext
   )
   ;

kennwert:
      'FESTWERT' n = nameValue '\n' info = kgr_info (ew = einheit_w)? (('WERT' r = realzahl) | ('TEXT' t = textValue)) '\n' 'END' ( '\n' )+
   ;

kennwerteblock
   : 'FESTWERTEBLOCK' n = nameValue ax = anzahl_x ('@' ay = anzahl_y)? '\n' info = kgr_info (ew = einheit_w)? (w += werteliste_kwb)+ 'END' ( '\n' )+
   ;

kennlinie:
   cat =  ('KENNLINIE' | 'FESTKENNLINIE' | 'GRUPPENKENNLINIE')
   n = nameValue ax = anzahl_x '\n' info = kgr_info (ex = einheit_x)? (ew = einheit_w)?
      (sst += sst_liste_x)+ (wl += werteliste)+ 'END' ('\n')+
   ;

kennfeld:
   cat = ('KENNFELD' | 'FESTKENNFELD' | 'GRUPPENKENNFELD')
   n = nameValue ax = anzahl_x ay = anzahl_y '\n' info = kgr_info (ex = einheit_x)? (ey = einheit_y)? (ew = einheit_w)?
      (sst += sst_liste_x)+ kf = kf_zeile_liste 'END' ('\n')+
   ;

gruppenstuetzstellen:
   'STUETZSTELLENVERTEILUNG' n = nameValue nx = anzahl_x '\n' info = kgr_info
   (ex = einheit_x)? (sl += sst_liste_x)+ 'END' ('\n')+
   ;

kenntext:
   'TEXTSTRING' n = nameValue '\n' info = kgr_info 'TEXT' t = textValue '\n' 'END' ('\n')+
   ;

kgr_info:
   (lname = langname)? (dname = displayname)? (var = var_abhangigkeiten)? (fkt = funktionszugehorigkeit)?
   ;

einheit_x:
   'EINHEIT_X' t = textValue '\n'
   ;

einheit_y:
   'EINHEIT_Y' t = textValue '\n'
   ;

einheit_w:
   'EINHEIT_W' t = textValue '\n'
   ;

langname:
   'LANGNAME' t = textValue '\n'
   ;

displayname:
   'DISPLAYNAME' (n = nameValue | t = textValue) '\n'
   ;

var_abhangigkeiten:
   'VAR' v += var_abh (',' v += var_abh)* '\n'
   ;

var_abh:
   NAME '=' n = nameValue
   ;

funktionszugehorigkeit:
   'FUNKTION' (n += nameValue)+ '\n'
   ;

anzahl_x:
   i = integerValue
   ;

anzahl_y:
   i = integerValue
   ;

werteliste:
   'WERT' (r += realzahl)+ '\n'
   ;

werteliste_kwb
   : (
           'WERT' (r += realzahl)+ '\n'
         | 'TEXT' (t += textValue)+ '\n')
   ;

sst_liste_x:
   (
         'ST/X' (r += realzahl)+ '\n'
      |  'ST_TX/X' (t += textValue)+ '\n'
   )
   ;

kf_zeile_liste:
   (
        (r += kf_zeile_liste_r)+
      | (t += kf_zeile_liste_tx)+
   )
   ;

kf_zeile_liste_r:
   ('ST/Y' r = realzahl '\n' (w += werteliste)+ )
   ;

kf_zeile_liste_tx:
   ('ST_TX/Y' t = textValue '\n' (w += werteliste)+ )
   ;

realzahl:
   (  i = INT | f = FLOAT )
   ;

nameValue:
    n = NAME
    ;

textValue:
    t = TEXT
    ;

integerValue:
   i = INT
   ;

///
///
///
NAME
   : NO_SO_VALID_C_IDENTIFIER_START ( NO_SO_VALID_C_IDENTIFIER )*
   ;

fragment NO_SO_VALID_C_IDENTIFIER_START
   : 'A' .. 'Z' | 'a' .. 'z' | '_'
   ;

fragment NO_SO_VALID_C_IDENTIFIER
   : 'A' .. 'Z' | 'a' .. 'z' | '_' | '0' .. '9' | '[' | ']' | '.'
   ;

fragment
EXPONENT : ('e'|'E') ('+'|'-')? ('0'..'9')+ ;

FLOAT:
   ('+' | '-')?
    (
        ('0'..'9')+ '.' ('0'..'9')* EXPONENT?
    |   '.' ('0'..'9')+ EXPONENT?
    |   ('0'..'9')+ EXPONENT
    | 'NaN'
    | 'INF'
    )
    ;

INT:
      ('+' | '-')? '0'..'9'+
    | '0'('x' | 'X') ('a' .. 'f' | 'A' .. 'F' | '0' .. '9')+
    ;


TEXT:
    '"' ( ESC_SEQ | ~('\\'|'"') )* '"'
    ;

fragment
ESC_SEQ
    :   '\\'
        (   // The standard escaped character set such as tab, newline, etc.
            [btnfr"'\\]
        |   // A Java style Unicode escape sequence
            UNICODE_ESC
        |   // Invalid escape
            .
        |   // Invalid escape at end of file
            EOF
        )
    ;

fragment
UNICODE_ESC
    :   'u' (HEX_DIGIT (HEX_DIGIT (HEX_DIGIT HEX_DIGIT?)?)?)?
;

fragment
HEX_DIGIT : ('0'..'9'|'a'..'f'|'A'..'F') ;

fragment
OCTAL_ESC:
    '\\' ('0'..'3') ('0'..'7') ('0'..'7')
    |   '\\' ('0'..'7') ('0'..'7')
    |   '\\' ('0'..'7')
    ;

fragment EscapeSequence
   : '\\' ( 'b' | 't' | 'n' | 'f' | 'r' | '\'' | '\\' ) // '\"'
   ;

WS
   : ( ' ' | '\r' | '\t' | '\u000C' ) ->skip
   ;


COMMENT:
    ('*' ~('\n'|'\r')* '\r'? '\n'
    |   '!' ~('\n'|'\r')* '\r'? '\n'
//    |   '!' ~('\n'|'\r')* '\r'? '\n'
    )
        -> channel(HIDDEN)
    ;
