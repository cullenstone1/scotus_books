names = [
  "barrett",
  "jackson",
  "alito",
  "gorsuch",
  "sotomayor",
  "kavanaugh",
  "thomas",
  "kagan",
  "roberts"
]

ids = [
  "delivered the opinion of the court",
  "concurring in judgement",
  "syllabus",
  ""
]

fonts = [
    "AAAAAB+Century-BoldItalic",          # title page
    "AAAAAC+CenturyExpandedSC-Regular",
    "AAAAAD+ArialMT",                     # "page print pre publication"
    "AAAAAE+CenturyExpanded",
    "AAAAAF+Century-Bold",
    "AAAAAG+CenturyExpanded",
    "AAAAAH+CenturyExpanded-Italic",
    "AAAAAI+CenturyExpandedSC-Regular",
    "AAAAAK+CenturyExpandedSC-Regular",
    "AAAAAL+CenturyExpanded",
    "AAAAAM+CenturyExpanded-Italic"
]

footnoteFontSize = 8.97
opinionFontSize = 10.97

# citationRegexes = [
#   r'\d+\s+\w+\.\s+\d+,\s+',
#   r'\d+\s+[Uu]\.\s+[Ss]\.\s+[Cc]\.\s+',
#   r'§.*?\.',
#   r'\d+\s+F\.\s+4th\s+\d+\s+\(\d{4}\);\s+\d+\s+U\.\s+S\.\s+–+–\s+\(\d{4}\)',
#   r'No\.\s+\d+:\d+.*?mc.*?\d+\s+\(.*?\),\s+ECF\s+Doc\.\s+\d+',
#   r'pp\.\s+\d+,\s+\d+',
#   r'Id\.,\s+at\s+\d+－'#\d+\.',
#   r'Id\.,\s+at\s+\d+–\d+\.'
# ]

all_hyphens = r'[\u002D\u00AD\u058A\u2010\u2011\u2012\u2013\u2014\u2015\u2E17\u2E1A\u301C\u30A0\uFE58\uFE63\uFF0D\u2043\u2212\u2500\u2501\u30FB]'
all_eol = r'\r\n|\r|\n'
expressions = {
  # maybe I don't actually care about removing case names?
  # "case_name": 'See\s+\D+\s+v\.\s+\D+\S',
  # "case_name": "\S[A-Za-z\s.'-]+\s+v\.\s+[A-Za-z\s.'-]+\S",
  "line_end_hyphen": all_hyphens + r'\n',
  "line_end": r'\r',
  "case_name_header": r'[A-Z]+.*?v\.\s+[A-Z]+ \n',
  "opinion_of_the_court": r'Opinion\s+of\s+the\s+Court\s+\n',
  "case_num_with_year": r'\d+\s+[Uu]\.\s+[Ss]\.\s+.*?\(.*?\)',
  "case_num": r'\d+\s+[Uu]\.\s+[Ss]\.\s+\d+',
  "ellipses": r'\.\s+\.\s+\.\s',
  "id_at_see_also_id_at": r'[Ii][Dd]\.,\s+at\s+\d+.*?[Ii][Dd]\.,\s+at\s+\d+',
  "id_at_multiple_pages": r'[Ii][Dd]\.,\s+at\s+\d+' + all_hyphens + '\d+',
  "id_at_with_page_nums": r'[Ii][Dd]\.,\s+at\s+\d+,\s+\d+' + all_hyphens + '\d+',
  "id_at_page_comma_page": r'[Ii][Dd]\.,\s+at\s+\d+,\s+\d+',
  "id_at": r'[Ii][Dd]\.,\s+at\s+\d+',
  "psychotic_case_num_cite1": r'\d+\s+[uU]\.\s+[Ss]\.,\s+\w+\s+\d+' + all_hyphens +'\d+,\s+\d+',
  "psychotic_case_num_cite2": r'\d+\s+[uU]\.\s+[Ss]\.,\s+\w+\s+\d+',
  "legal_character_cite": r'§.*?[. ]',
  "multiple_legal_character_cite": r'§§.*?[.]',
  "usc_cite": r'\d+\s+U\.\s+S\.\s+C\.',
  # "justice_delivered": '\w+,\s+J\.,\s+delivered\s+the\s+opinion',
  "ibid": r'[Ii][bB][iI][dD]',
  # "quotation_marks_omitted": '\(internal\s+quotation\s+marks\s+omitted\)',
  "another_cite": r'\d+\s+\w+\.\s+\d+\w+\s+\d+\s+\(.*?\);\s+\d+.*?\(.*?\)',
  "cite_as": r'Cite\s+as.*?\n',
  "stat": r'\s+\d+.*?et\s+seq',
  "page_nums": r'\n\d+ \n',
  "pp_nums": r'\s+pp\.\s+\d+,\s+\d+',
  "pp_num": r'\s+pp\.\s+\d+',
  "no_blank": r'\s+No\.\s+\d+:\d+' + all_hyphens + r'\w+' + all_hyphens + r'\d+\s+\(.*?\)',
  "ecf_doc_extra": r'ECF\s+Doc\.\s+\d+[\.,].*?\.',
  "ecf_doc_plain": r'ECF\s+Doc\.\s+\d+[\.,]',
  "period_space_period": r'[\.,]\s+(?=[\.,])',
  "page_proof": r'Page\s+Proof.*?\n',
  "superscript": r'[1-9*] \n',
  "short_cite": r'\d+\(.*?\)',
  "justice_dissenting": r'\(\w+,\s+J\.,\s+.*?\s+.*?\)',
  "triple_parenthesis": r'\(.*?\)\(.*?\)\(.*?\)',
  "num_f_num": r'\s+\d+\s+\w+\.\s+\d+\w+\s+\d+,\s+\d+,\s+\w+\.\s+\d+\s+\(.*?\d+\)',
  "in_no": r'in\s+No\.\s+\d+' + all_hyphens + r'\d+\s+\(.*?\)',
  "p_n_no": r'[pn]\.\s+\d+[,\.]',
  "justice_concurring": r'\w+,\s+J\.,\s+concurring\s+in\s+judgment\s+',
  "justice_dissenting": r'\w+,\s+J\.,\s+dissenting\s+in\s+judgment\s+',
  "post_at": r'[Pp]ost,\s+at.*?\.',
  "post_at_newline": r'[Pp]ost,\s+at.*?\s+.*?\.',
  "per_curiam": r'\(per\s+curiam\)',
  "parenthetical_year": r'\(\d{4}\)',
  "parenthetical_year_with_stuff": r'\(.*?\d{4}\)',
  "parenthetical_year_with_stuff": r'\(.*?\d{4}\)',
  "num_us_dash_dash": r'\d+\s+[Uu]\.\s+[sS]\.\s+' + all_hyphens + r',\s+' + all_hyphens + r'\s+',
  "parenthesis_concurring": r'\(.*?concurring\)',
  "parenthesis_dissenting": r'\(.*?dissenting\)',
  "leftover_dots": r'\s+[,\.;]\s+',
}