import re
from pdfminer.high_level import extract_text
from pdfminer.high_level import extract_text_to_fp
from pdfminer.high_level import extract_pages
from io import StringIO
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage

# Define the regular expression pattern for an email address
email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

# expression = '\D+\s+v\.\D+,\d+\s+\D+\.\D+\.\s+(.*?)\s+\d+\s+(.*?)'
# see = 
# this one matches name v. name type case names
case_name = '\w+\s+v\.\s+\w+,\s+'
# case_name = '\d+\s+\w+\.\w+\.\s+\(.*?\)\s+\d+\s+\(.*?\)'
# this matches num U.S. num type case nums
case_num = '\d+\s+[Uu]\.\s+[Ss]\.\s+\d+'
year_after_case_num = '\s+\(.*?\)'
full_cite_case_num = '\d+\s+\w+\.\s+\w+\.\s+\d+'
all_hyphens = '[-‐‑‒–—―−]'

expressions = {
  # maybe I don't actually care about removing case names?
  # "case_name": 'See\s+\D+\s+v\.\s+\D+\S',
  # "case_name": "\S[A-Za-z\s.'-]+\s+v\.\s+[A-Za-z\s.'-]+\S",
  "case_num_with_year": '\d+\s+[Uu]\.\s+[Ss]\.\s+\d+\s+\(.*?\)',
  "case_num": '\d+\s+[Uu]\.\s+[Ss]\.\s+\d+',
  "id_at_see_also_id_at": '[Ii][Dd]\.,\s+at\s+\d+.*?[Ii][Dd]\.,\s+at\s+\d+',
  "id_at_multiple_pages": '[Ii][Dd]\.,\s+at\s+\d+' + all_hyphens + '\d+',
  "id_at_with_page_nums": '[Ii][Dd]\.,\s+at\s+\d+,\s+\d+' + all_hyphens + '\d+',
  "id_at": '[Ii][Dd]\.,\s+at\s+\d+',
  "psychotic_case_num_cite1": '\d+\s+[uU]\.\s+[Ss]\.,\s+\w+\s+\d+' + all_hyphens +'\d+,\s+\d+',
  "psychotic_case_num_cite2": '\d+\s+[uU]\.\s+[Ss]\.,\s+\w+\s+\d+',
  "legal_character_cite": '§.*?[. ]',
  "multiple_legal_character_cite": '§§.*?[.]',
  "usc_cite": '\d+\s+U\.\s+S\.\s+C\.',
  # "justice_delivered": '\w+,\s+J\.,\s+delivered\s+the\s+opinion',
  "ibid": '[Ii][bB][iI][dD]',
  # "quotation_marks_omitted": '\(internal\s+quotation\s+marks\s+omitted\)',
}
# Define a function to extract text from a PDF and find all emails
def extract_emails_from_pdf(pdf_path):
    # Extract text from the PDF
    text = extract_text(pdf_path)
    pages_text = []
    pages = extract_pages(pdf_path)    # Extract pages from the PDF
    for page_layout in pages:
        # Create a StringIO object to capture the extracted text
        output_string = StringIO()
        # Perform layout analysis
        # this is just a default laparams
        # laparams is probably very useful in discerning footnotes from body text
        laparams = LAParams()
        # Extract text to the StringIO object
        extract_text_to_fp(output_string, page_layout, laparams=laparams)
        # Get the text from the StringIO object
        page_text = output_string.getvalue()
        # Append the page text to the list
        pages_text.append(page_text)
    
    # Use re.findall() to find all email addresses in the text
    emails = re.findall(expressions["legal_character_cite"], text)
    
    return emails

# Specify the path to your PDF file
pdf_path = '22-529_1b7d.pdf'

# Extract and print the email addresses
emails = extract_emails_from_pdf(pdf_path)

print("Email addresses found:")
for email in emails:
    print(email)
print(len(emails))
