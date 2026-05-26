/*
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2025 by Christoph Schueler <cpu12.gems@googlemail.com>

   Hand-written recursive-descent DCM 2.0 parser exposed via pybind11.
   Replaces the ANTLR4-generated parser and Dcm20Listener.

   License: GNU General Public License v2 or later (GPLv2+)
*/

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cctype>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace py = pybind11;
using namespace py::literals;

// ============================================================
// Token kinds
// ============================================================

enum class Tok {
    // keywords
    KONSERVIERUNG_FORMAT,
    MODULKOPF, FUNKTIONEN, FKT,
    VARIANTENKODIERUNG, KRITERIUM,
    FESTWERT, FESTWERTEBLOCK,
    KENNLINIE, FESTKENNLINIE, GRUPPENKENNLINIE,
    KENNFELD, FESTKENNFELD, GRUPPENKENNFELD,
    STUETZSTELLENVERTEILUNG, TEXTSTRING,
    EINHEIT_X, EINHEIT_Y, EINHEIT_W,
    LANGNAME, DISPLAYNAME,
    VAR, FUNKTION,
    WERT, TEXT, END,
    STX, STTX_X, STY, STTX_Y,
    // literals
    NAME, FLOAT_LIT, INT_LIT, TEXT_LIT,
    // structural
    NL, AT, COMMA, EQ,
    EOF_T
};

struct Token {
    Tok   kind;
    std::string text;
    int   line, col;
};

// ============================================================
// Lexer
// ============================================================

class Lexer {
    std::string src_;
    size_t      pos_ = 0;
    int         line_ = 1, col_ = 1;

    static const std::unordered_map<std::string, Tok>& kw_map() {
        static const std::unordered_map<std::string, Tok> m = {
            {"KONSERVIERUNG_FORMAT", Tok::KONSERVIERUNG_FORMAT},
            {"MODULKOPF",            Tok::MODULKOPF},
            {"FUNKTIONEN",           Tok::FUNKTIONEN},
            {"FKT",                  Tok::FKT},
            {"END",                  Tok::END},
            {"VARIANTENKODIERUNG",   Tok::VARIANTENKODIERUNG},
            {"KRITERIUM",            Tok::KRITERIUM},
            {"FESTWERT",             Tok::FESTWERT},
            {"FESTWERTEBLOCK",       Tok::FESTWERTEBLOCK},
            {"KENNLINIE",            Tok::KENNLINIE},
            {"FESTKENNLINIE",        Tok::FESTKENNLINIE},
            {"GRUPPENKENNLINIE",     Tok::GRUPPENKENNLINIE},
            {"KENNFELD",             Tok::KENNFELD},
            {"FESTKENNFELD",         Tok::FESTKENNFELD},
            {"GRUPPENKENNFELD",      Tok::GRUPPENKENNFELD},
            {"STUETZSTELLENVERTEILUNG", Tok::STUETZSTELLENVERTEILUNG},
            {"TEXTSTRING",           Tok::TEXTSTRING},
            {"EINHEIT_X",            Tok::EINHEIT_X},
            {"EINHEIT_Y",            Tok::EINHEIT_Y},
            {"EINHEIT_W",            Tok::EINHEIT_W},
            {"LANGNAME",             Tok::LANGNAME},
            {"DISPLAYNAME",          Tok::DISPLAYNAME},
            {"VAR",                  Tok::VAR},
            {"FUNKTION",             Tok::FUNKTION},
            {"WERT",                 Tok::WERT},
            {"TEXT",                 Tok::TEXT},
            {"ST/X",                 Tok::STX},
            {"ST_TX/X",              Tok::STTX_X},
            {"ST/Y",                 Tok::STY},
            {"ST_TX/Y",              Tok::STTX_Y},
        };
        return m;
    }

    char cur(int off = 0) const {
        size_t p = pos_ + off;
        return p < src_.size() ? src_[p] : '\0';
    }

    char adv() {
        char c = src_[pos_++];
        if (c == '\n') { ++line_; col_ = 1; } else ++col_;
        return c;
    }

    void skip_ws() {
        while (pos_ < src_.size()) {
            char c = cur();
            if (c == ' ' || c == '\t' || c == '\r' || c == '\f') adv();
            else break;
        }
    }

    Token read_string(int sl, int sc) {
        // pos_ is after the opening quote
        std::string s = "\"";
        while (pos_ < src_.size()) {
            char c = cur();
            if (c == '\\') {
                s += adv();
                if (pos_ < src_.size()) s += adv();
            } else if (c == '"') {
                s += adv();
                break;
            } else {
                s += adv();
            }
        }
        return {Tok::TEXT_LIT, s, sl, sc};
    }

    Token read_name(int sl, int sc) {
        std::string s;
        while (pos_ < src_.size()) {
            char c = cur();
            if (std::isalnum((unsigned char)c) || c == '_' || c == '.' || c == '[' || c == ']')
                s += adv();
            else
                break;
        }
        // Handle ST/X, ST/Y, ST_TX/X, ST_TX/Y
        if (cur() == '/' && (s == "ST" || s == "ST_TX")) {
            char next = cur(1);
            if (next == 'X' || next == 'Y') {
                std::string combined = s + "/" + next;
                auto it = kw_map().find(combined);
                if (it != kw_map().end()) {
                    adv(); adv(); // consume /X or /Y
                    return {it->second, combined, sl, sc};
                }
            }
        }
        // NaN and INF are float literals
        if (s == "NaN" || s == "INF") return {Tok::FLOAT_LIT, s, sl, sc};

        auto it = kw_map().find(s);
        if (it != kw_map().end()) return {it->second, s, sl, sc};
        return {Tok::NAME, s, sl, sc};
    }

    Token read_number(int sl, int sc) {
        std::string s;
        bool is_float = false;

        if (cur() == '+' || cur() == '-') s += adv();

        // Hex integer
        if (cur() == '0' && (cur(1) == 'x' || cur(1) == 'X')) {
            s += adv(); s += adv();
            while (pos_ < src_.size() && std::isxdigit((unsigned char)cur())) s += adv();
            return {Tok::INT_LIT, s, sl, sc};
        }

        while (pos_ < src_.size() && std::isdigit((unsigned char)cur())) s += adv();

        if (cur() == '.') {
            // Only consume dot if it's followed by a digit, or we already have digits
            if (std::isdigit((unsigned char)cur(1)) || !s.empty()) {
                is_float = true;
                s += adv();
                while (pos_ < src_.size() && std::isdigit((unsigned char)cur())) s += adv();
            }
        }

        if (cur() == 'e' || cur() == 'E') {
            is_float = true;
            s += adv();
            if (cur() == '+' || cur() == '-') s += adv();
            while (pos_ < src_.size() && std::isdigit((unsigned char)cur())) s += adv();
        }

        return {is_float ? Tok::FLOAT_LIT : Tok::INT_LIT, s, sl, sc};
    }

public:
    explicit Lexer(std::string src) : src_(std::move(src)) {}

    std::vector<Token> tokenize() {
        std::vector<Token> toks;
        while (true) {
            skip_ws();
            if (pos_ >= src_.size()) {
                toks.push_back({Tok::EOF_T, "", line_, col_});
                break;
            }
            int sl = line_, sc = col_;
            char c = cur();

            if (c == '\n') {
                adv();
                toks.push_back({Tok::NL, "\n", sl, sc});
            } else if (c == '*' || c == '!') {
                while (pos_ < src_.size() && cur() != '\n') adv();
            } else if (c == '"') {
                adv();
                toks.push_back(read_string(sl, sc));
            } else if (c == '@') {
                adv();
                toks.push_back({Tok::AT, "@", sl, sc});
            } else if (c == ',') {
                adv();
                toks.push_back({Tok::COMMA, ",", sl, sc});
            } else if (c == '=') {
                adv();
                toks.push_back({Tok::EQ, "=", sl, sc});
            } else if (c == '+' || c == '-') {
                toks.push_back(read_number(sl, sc));
            } else if (std::isdigit((unsigned char)c)) {
                toks.push_back(read_number(sl, sc));
            } else if (c == '.' && std::isdigit((unsigned char)cur(1))) {
                toks.push_back(read_number(sl, sc));
            } else if (std::isalpha((unsigned char)c) || c == '_') {
                toks.push_back(read_name(sl, sc));
            } else {
                adv(); // skip unknown characters
            }
        }
        return toks;
    }
};

// ============================================================
// Parser
// ============================================================

class Parser {
    std::vector<Token> toks_;
    size_t             pos_ = 0;
    py::object         decimal_type_;

    py::object decimal(const std::string& s) {
        if (!decimal_type_)
            decimal_type_ = py::module_::import("decimal").attr("Decimal");
        return decimal_type_(s);
    }

    const Token& cur() const { return toks_[pos_]; }

    const Token& lookahead(int off = 1) const {
        size_t p = pos_ + off;
        return p < toks_.size() ? toks_[p] : toks_.back();
    }

    bool at(Tok k) const { return cur().kind == k; }

    void eat_nls() {
        while (at(Tok::NL)) ++pos_;
    }

    bool try_eat(Tok k) {
        if (at(k)) { ++pos_; return true; }
        return false;
    }

    Token eat(Tok k) {
        if (!at(k)) {
            throw std::runtime_error(
                "DCM parse error at line " + std::to_string(cur().line) +
                ": expected token kind " + std::to_string(static_cast<int>(k)) +
                " but got '" + cur().text + "'");
        }
        return toks_[pos_++];
    }

    // ----------------------------------------------------------------
    // Primitive parsers
    // ----------------------------------------------------------------

    std::string parse_name() { return eat(Tok::NAME).text; }

    std::string parse_text_value() {
        auto t = eat(Tok::TEXT_LIT);
        std::string s = t.text;
        if (s.size() >= 2 && s.front() == '"' && s.back() == '"')
            s = s.substr(1, s.size() - 2);
        // Process simple escape sequences
        std::string out;
        out.reserve(s.size());
        for (size_t i = 0; i < s.size(); ++i) {
            if (s[i] == '\\' && i + 1 < s.size()) {
                char esc = s[++i];
                switch (esc) {
                    case 'n':  out += '\n'; break;
                    case 't':  out += '\t'; break;
                    case 'r':  out += '\r'; break;
                    case '"':  out += '"';  break;
                    case '\\': out += '\\'; break;
                    default:   out += '\\'; out += esc; break;
                }
            } else {
                out += s[i];
            }
        }
        return out;
    }

    int parse_integer() {
        if (!at(Tok::INT_LIT))
            throw std::runtime_error(
                "DCM parse error at line " + std::to_string(cur().line) + ": expected integer");
        auto t = eat(Tok::INT_LIT);
        return static_cast<int>(std::stol(t.text, nullptr, 0));
    }

    py::object parse_realzahl() {
        if (at(Tok::FLOAT_LIT)) return decimal(eat(Tok::FLOAT_LIT).text);
        if (at(Tok::INT_LIT))   return decimal(eat(Tok::INT_LIT).text);
        throw std::runtime_error(
            "DCM parse error at line " + std::to_string(cur().line) + ": expected number");
    }

    bool is_realzahl() const { return at(Tok::FLOAT_LIT) || at(Tok::INT_LIT); }

    // ----------------------------------------------------------------
    // kgr_info
    // ----------------------------------------------------------------

    py::dict parse_kgr_info() {
        py::object langname    = py::none();
        py::object displayname = py::none();
        py::object var_abh     = py::none();
        py::object funktion    = py::none();

        if (at(Tok::LANGNAME)) {
            ++pos_;
            langname = py::cast(parse_text_value());
            eat(Tok::NL);
        }

        if (at(Tok::DISPLAYNAME)) {
            ++pos_;
            std::string nv_str, tv_str;
            bool has_nv = false, has_tv = false;
            if (at(Tok::NAME))     { nv_str = parse_name();       has_nv = true; }
            else if (at(Tok::TEXT_LIT)) { tv_str = parse_text_value(); has_tv = true; }
            eat(Tok::NL);
            py::dict d;
            d["name_value"] = has_nv ? py::cast(nv_str) : py::none();
            d["text_value"] = has_tv ? py::cast(tv_str) : py::none();
            displayname = d;
        }

        if (at(Tok::VAR)) {
            ++pos_;
            py::list vlist;
            // var_abh: NAME = NAME
            eat(Tok::NAME); // criterion name (consumed but not stored per listener)
            eat(Tok::EQ);
            vlist.append(py::cast(parse_name()));
            while (at(Tok::COMMA)) {
                ++pos_;
                eat(Tok::NAME);
                eat(Tok::EQ);
                vlist.append(py::cast(parse_name()));
            }
            eat(Tok::NL);
            var_abh = vlist;
        }

        if (at(Tok::FUNKTION)) {
            ++pos_;
            py::list flist;
            while (at(Tok::NAME)) flist.append(py::cast(parse_name()));
            eat(Tok::NL);
            funktion = flist;
        }

        py::dict info;
        info["langname"]             = langname;
        info["displayname"]          = displayname;
        info["var_abhangigkeiten"]   = var_abh;
        info["funktionszugehorigkeit"] = funktion;
        return info;
    }

    // ----------------------------------------------------------------
    // Optional unit parsers
    // ----------------------------------------------------------------

    py::object parse_einheit(Tok kw) {
        if (!at(kw)) return py::none();
        ++pos_;
        auto s = parse_text_value();
        eat(Tok::NL);
        return py::cast(s);
    }

    // ----------------------------------------------------------------
    // sst_liste_x: ST/X realzahl+ NL | ST_TX/X textValue+ NL
    // ----------------------------------------------------------------

    py::dict parse_sst_liste_x() {
        bool is_real = at(Tok::STX);
        ++pos_; // consume ST/X or ST_TX/X
        py::list rs, ts;
        if (is_real) {
            while (is_realzahl()) rs.append(parse_realzahl());
        } else {
            while (at(Tok::TEXT_LIT)) ts.append(py::cast(parse_text_value()));
        }
        eat(Tok::NL);
        py::dict d;
        d["category"] = py::cast(std::string(is_real ? "REAL" : "TEXT"));
        d["rs"] = rs;
        d["ts"] = ts;
        return d;
    }

    // ----------------------------------------------------------------
    // werteliste: WERT realzahl+ NL
    // ----------------------------------------------------------------

    py::list parse_werteliste() {
        eat(Tok::WERT);
        py::list rs;
        while (is_realzahl()) rs.append(parse_realzahl());
        eat(Tok::NL);
        return rs;
    }

    // werteliste_kwb: (WERT realzahl+ | TEXT textValue+) NL
    py::dict parse_werteliste_kwb() {
        bool is_wert = at(Tok::WERT);
        ++pos_; // consume WERT or TEXT
        py::list rs, ts;
        if (is_wert) {
            while (is_realzahl()) rs.append(parse_realzahl());
        } else {
            while (at(Tok::TEXT_LIT)) ts.append(py::cast(parse_text_value()));
        }
        eat(Tok::NL);
        py::dict d;
        d["category"] = py::cast(std::string(is_wert ? "WERT" : "TEXT"));
        d["rs"] = rs;
        d["ts"] = ts;
        return d;
    }

    // ----------------------------------------------------------------
    // FESTWERT
    // ----------------------------------------------------------------

    py::dict parse_kennwert() {
        eat(Tok::FESTWERT);
        auto name = parse_name();
        eat(Tok::NL);
        auto info = parse_kgr_info();
        auto ew   = parse_einheit(Tok::EINHEIT_W);

        py::object realzahl = py::none();
        py::object text_val = py::none();
        std::string category;

        if (at(Tok::WERT)) {
            ++pos_;
            realzahl = parse_realzahl();
            category = "REAL";
        } else if (at(Tok::TEXT)) {
            ++pos_;
            text_val = py::cast(parse_text_value());
            category = "TEXT";
        }
        eat(Tok::NL);
        eat(Tok::END);
        eat_nls();

        py::dict d;
        d["category"]  = py::cast(category);
        d["name"]      = py::cast(name);
        d["info"]      = info;
        d["einheit_w"] = ew;
        d["realzahl"]  = realzahl;
        d["text"]      = text_val;
        return d;
    }

    // ----------------------------------------------------------------
    // FESTWERTEBLOCK
    // ----------------------------------------------------------------

    py::dict parse_kennwerteblock() {
        eat(Tok::FESTWERTEBLOCK);
        auto name = parse_name();
        auto ax   = parse_integer();
        int  ay   = 0;
        if (at(Tok::AT)) { ++pos_; ay = parse_integer(); }
        eat(Tok::NL);
        auto info = parse_kgr_info();
        auto ew   = parse_einheit(Tok::EINHEIT_W);

        py::list wl;
        while (at(Tok::WERT) || at(Tok::TEXT)) wl.append(parse_werteliste_kwb());

        eat(Tok::END);
        eat_nls();

        py::dict d;
        d["name"]           = py::cast(name);
        d["anzahl_x"]       = py::cast(ax);
        d["anzahl_y"]       = py::cast(ay);
        d["info"]           = info;
        d["einheit_w"]      = ew;
        d["werteliste_kwb"] = wl;
        return d;
    }

    // ----------------------------------------------------------------
    // KENNLINIE / FESTKENNLINIE / GRUPPENKENNLINIE
    // ----------------------------------------------------------------

    py::dict parse_kennlinie() {
        std::string cat = cur().text;
        ++pos_; // consume keyword
        auto name = parse_name();
        auto ax   = parse_integer();
        eat(Tok::NL);
        auto info = parse_kgr_info();
        auto ex   = parse_einheit(Tok::EINHEIT_X);
        auto ew   = parse_einheit(Tok::EINHEIT_W);

        py::list sst_list, wl_list;
        while (at(Tok::STX) || at(Tok::STTX_X)) sst_list.append(parse_sst_liste_x());
        while (at(Tok::WERT))                    wl_list.append(parse_werteliste());

        eat(Tok::END);
        eat_nls();

        py::dict d;
        d["category"]    = py::cast(cat);
        d["name"]        = py::cast(name);
        d["anzahl_x"]    = py::cast(ax);
        d["info"]        = info;
        d["einheit_x"]   = ex;
        d["einheit_w"]   = ew;
        d["sst_liste_x"] = sst_list;
        d["werteliste"]  = wl_list;
        return d;
    }

    // ----------------------------------------------------------------
    // kf_zeile_liste
    // ----------------------------------------------------------------

    py::dict parse_kf_zeile_liste() {
        py::list rs, ts;
        bool is_real = true;

        if (at(Tok::STY)) {
            while (at(Tok::STY)) {
                ++pos_;
                auto r = parse_realzahl();
                eat(Tok::NL);
                py::list wl;
                while (at(Tok::WERT)) wl.append(parse_werteliste());
                py::dict row;
                row["realzahl"]   = r;
                row["werteliste"] = wl;
                rs.append(row);
            }
        } else if (at(Tok::STTX_Y)) {
            is_real = false;
            while (at(Tok::STTX_Y)) {
                ++pos_;
                auto t = parse_text_value();
                eat(Tok::NL);
                py::list wl;
                while (at(Tok::WERT)) wl.append(parse_werteliste());
                py::dict row;
                row["text"]       = py::cast(t);
                row["werteliste"] = wl;
                ts.append(row);
            }
        }

        py::dict d;
        d["category"] = py::cast(std::string(is_real ? "REAL" : "TEXT"));
        d["rs"]       = rs;
        d["ts"]       = ts;
        return d;
    }

    // ----------------------------------------------------------------
    // KENNFELD / FESTKENNFELD / GRUPPENKENNFELD
    // ----------------------------------------------------------------

    py::dict parse_kennfeld() {
        std::string cat = cur().text;
        ++pos_;
        auto name = parse_name();
        auto ax   = parse_integer();
        auto ay   = parse_integer();
        eat(Tok::NL);
        auto info = parse_kgr_info();
        auto ex   = parse_einheit(Tok::EINHEIT_X);
        auto ey   = parse_einheit(Tok::EINHEIT_Y);
        auto ew   = parse_einheit(Tok::EINHEIT_W);

        py::list sst_list;
        while (at(Tok::STX) || at(Tok::STTX_X)) sst_list.append(parse_sst_liste_x());

        auto kf_zeile = parse_kf_zeile_liste();

        eat(Tok::END);
        eat_nls();

        py::dict d;
        d["category"]      = py::cast(cat);
        d["name"]          = py::cast(name);
        d["anzahl_x"]      = py::cast(ax);
        d["anzahl_y"]      = py::cast(ay);
        d["info"]          = info;
        d["einheit_x"]     = ex;
        d["einheit_y"]     = ey;
        d["einheit_w"]     = ew;
        d["sst_liste_x"]   = sst_list;
        d["kf_zeile_liste"] = kf_zeile;
        return d;
    }

    // ----------------------------------------------------------------
    // STUETZSTELLENVERTEILUNG
    // ----------------------------------------------------------------

    py::dict parse_gruppenstuetzstellen() {
        eat(Tok::STUETZSTELLENVERTEILUNG);
        auto name = parse_name();
        auto nx   = parse_integer();
        eat(Tok::NL);
        auto info = parse_kgr_info();
        auto ex   = parse_einheit(Tok::EINHEIT_X);

        py::list sst_list;
        while (at(Tok::STX) || at(Tok::STTX_X)) sst_list.append(parse_sst_liste_x());

        eat(Tok::END);
        eat_nls();

        py::dict d;
        d["name"]        = py::cast(name);
        d["anzahl_x"]    = py::cast(nx);
        d["info"]        = info;
        d["einheit_x"]   = ex;
        d["sst_liste_x"] = sst_list;
        return d;
    }

    // ----------------------------------------------------------------
    // TEXTSTRING
    // ----------------------------------------------------------------

    py::dict parse_kenntext() {
        eat(Tok::TEXTSTRING);
        auto name = parse_name();
        eat(Tok::NL);
        auto info = parse_kgr_info();
        eat(Tok::TEXT);
        auto text = parse_text_value();
        eat(Tok::NL);
        eat(Tok::END);
        eat_nls();

        py::dict d;
        d["name"] = py::cast(name);
        d["info"] = info;
        d["text"] = py::cast(text);
        return d;
    }

    // ----------------------------------------------------------------
    // kenngroesse dispatcher
    // ----------------------------------------------------------------

    py::dict parse_kenngroesse() {
        py::object kw  = py::none(), kwb = py::none(), kl = py::none();
        py::object kf  = py::none(), gst = py::none(), kt = py::none();

        switch (cur().kind) {
            case Tok::FESTWERT:              kw  = parse_kennwert();          break;
            case Tok::FESTWERTEBLOCK:        kwb = parse_kennwerteblock();    break;
            case Tok::KENNLINIE:
            case Tok::FESTKENNLINIE:
            case Tok::GRUPPENKENNLINIE:      kl  = parse_kennlinie();         break;
            case Tok::KENNFELD:
            case Tok::FESTKENNFELD:
            case Tok::GRUPPENKENNFELD:       kf  = parse_kennfeld();          break;
            case Tok::STUETZSTELLENVERTEILUNG: gst = parse_gruppenstuetzstellen(); break;
            case Tok::TEXTSTRING:            kt  = parse_kenntext();          break;
            default:
                throw std::runtime_error(
                    "DCM parse error at line " + std::to_string(cur().line) +
                    ": unexpected token '" + cur().text + "'");
        }

        py::dict d;
        d["kw"]  = kw;
        d["kwb"] = kwb;
        d["kl"]  = kl;
        d["kf"]  = kf;
        d["gst"] = gst;
        d["kt"]  = kt;
        return d;
    }

    // ----------------------------------------------------------------
    // Header: MODULKOPF, FUNKTIONEN, VARIANTENKODIERUNG
    // ----------------------------------------------------------------

    py::object parse_modulkopf_info() {
        py::list m;
        while (at(Tok::MODULKOPF)) {
            // Disambiguate: anf = MODULKOPF NAME TEXT NL
            //               fort = MODULKOPF TEXT NL
            if (lookahead(1).kind != Tok::NAME) break; // not an anf line

            ++pos_; // consume MODULKOPF
            auto name = parse_name();
            auto wert = parse_text_value();
            eat(Tok::NL);

            py::dict anf;
            anf["name"] = py::cast(name);
            anf["wert"] = py::cast(wert);

            py::list fort;
            while (at(Tok::MODULKOPF) && lookahead(1).kind == Tok::TEXT_LIT) {
                ++pos_; // consume MODULKOPF
                fort.append(py::cast(parse_text_value()));
                eat(Tok::NL);
            }

            py::dict zeile;
            zeile["anf"]  = anf;
            zeile["fort"] = fort;
            m.append(zeile);
        }
        if (py::len(m) == 0) return py::none();
        return m;
    }

    py::object parse_funktionsdef() {
        if (!at(Tok::FUNKTIONEN)) return py::none();
        ++pos_;
        eat(Tok::NL);
        py::list flist;
        while (at(Tok::FKT)) {
            ++pos_;
            auto name    = parse_name();
            auto version = parse_text_value();
            auto langname = parse_text_value();
            eat(Tok::NL);
            py::dict f;
            f["name"]    = py::cast(name);
            f["version"] = py::cast(version);
            f["langname"] = py::cast(langname);
            flist.append(f);
        }
        eat(Tok::END);
        eat_nls();
        return flist;
    }

    py::object parse_variantendef() {
        if (!at(Tok::VARIANTENKODIERUNG)) return py::none();
        ++pos_;
        eat(Tok::NL);
        py::list vlist;
        while (at(Tok::KRITERIUM)) {
            ++pos_;
            auto name = parse_name();
            py::list werte;
            while (at(Tok::NAME)) werte.append(py::cast(parse_name()));
            eat(Tok::NL);
            py::dict krit;
            krit["name"]  = py::cast(name);
            krit["werte"] = werte;
            vlist.append(krit);
        }
        eat(Tok::END);
        eat_nls();
        return vlist;
    }

public:
    explicit Parser(std::vector<Token> toks) : toks_(std::move(toks)) {}

    py::dict parse() {
        eat_nls();

        // file_format
        py::object version = py::none();
        if (at(Tok::KONSERVIERUNG_FORMAT)) {
            ++pos_;
            if (at(Tok::FLOAT_LIT)) {
                version = py::cast(std::stod(toks_[pos_++].text));
            } else if (at(Tok::INT_LIT)) {
                version = py::cast(static_cast<double>(std::stol(toks_[pos_++].text)));
            }
            eat_nls();
        }

        // kons_kopf
        auto info     = parse_modulkopf_info();
        auto func_def = parse_funktionsdef();
        auto var_def  = parse_variantendef();

        py::dict kopf;
        kopf["info"]     = info;
        kopf["func_def"] = func_def;
        kopf["var_def"]  = var_def;

        // kons_rumpf
        py::list rumpf;
        eat_nls();
        while (!at(Tok::EOF_T)) {
            try {
                rumpf.append(parse_kenngroesse());
            } catch (const std::exception&) {
                ++pos_; // skip bad token and try to recover
                eat_nls();
            }
        }

        py::dict result;
        result["version"] = version;
        result["kopf"]    = kopf;
        result["rumpf"]   = rumpf;
        return result;
    }
};

// ============================================================
// Public C++ API
// ============================================================

static py::dict do_parse(const std::string& text) {
    Lexer lexer(text);
    auto  tokens = lexer.tokenize();
    return Parser(std::move(tokens)).parse();
}

py::dict parse_dcm_string(const std::string& text) {
    return do_parse(text);
}

// File reading is delegated to Python (caller) for correct encoding handling.
// This overload is provided as a convenience that reads with binary mode
// (suitable for latin-1 content).
py::dict parse_dcm_file_bytes(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot open file: " + path);
    std::string content((std::istreambuf_iterator<char>(f)), {});
    return do_parse(content);
}

// ============================================================
// pybind11 module
// ============================================================

PYBIND11_MODULE(_dcm_parser, m) {
    m.doc() = "DCM 2.0 parser — hand-written C++ implementation";
    m.def("parse_string",
          &parse_dcm_string,
          py::arg("text"),
          "Parse DCM 2.0 text (str) and return a structured dict.");
    m.def("parse_file_bytes",
          &parse_dcm_file_bytes,
          py::arg("path"),
          "Parse a DCM 2.0 file reading raw bytes (latin-1 compatible).");
}
