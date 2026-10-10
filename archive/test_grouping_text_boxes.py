import sys
from pdfminer.high_level import extract_pages
from io import StringIO
from pdfminer.layout import LTTextContainer, LTChar, LTTextLine, LAParams, LTLine

def SeparateAndPrintTextBoxes(filename):
  # with open(filename, 'r') as f:
  params = LAParams()
  params.line_margin = 0.7
  pages = extract_pages(filename, laparams=params)
  line_y_pos = 0.0
  # for pageLayout in pages:
  for element in list(pages)[3]:
    if isinstance(element, LTLine):
      print(f"GOT A LINE {element.x0, element.y0}\n\n")
      line_y_pos = element.y0

  pages = extract_pages(filename, laparams=params)
  if (line_y_pos > 0):
    for element in list(pages)[3]:
      if isinstance(element, LTTextContainer):
        if (element.y0 > line_y_pos):
          print(element.get_text())
          print(f"got new text element {element.x0, element.y0}\n")


if __name__ == '__main__':
  SeparateAndPrintTextBoxes(sys.argv[1])