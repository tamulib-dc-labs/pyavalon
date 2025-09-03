from fpdf import FPDF
from weasyprint import HTML
import os


class HTMLPDFBuilder:
    def __init__(self, metadata={}, collection="Unnamed Collection", output_filename="output.pdf", vtt=None):
        self.output = output_filename
        self.vtt = vtt
        self.collection_title = collection
        self.elements = metadata
        self.warning = True
        self.transcript_lines = self.__add_vtt()
        self.collection = collection

    def __add_vtt(self):
        if not self.vtt or not os.path.exists(self.vtt):
            return
        skip_phrases = [
            "WEBVTT", "Type:", "Language:", "Responsible Party:",
            "Originating File:", "File Creator:", "File Creation Date:", "Local Usage Element:"
        ]
        lines = []
        with open(self.vtt, 'r') as vtt_file:
            for line in vtt_file:
                if not any(phrase in line for phrase in skip_phrases):
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
        return lines

    def build_html(self, title, language="en-US"):
        # @TODO: Clean up Font imports and think about how to bundle its requrements for reuse.
        html = f"""
        <html lang={language}>
        <head>
            <meta charset="utf-8">
            <title>{title}</title>
            <style>
                @font-face {{
                    font-family: 'Oswald';
                    src: url('fonts/static/Oswald-Regular.ttf') format('truetype');
                    font-weight: normal;
                    font-style: normal;
                }}
                @font-face {{
                    font-family: 'CrimsonText';
                    src: url('fonts/crimson/Crimson_Text/CrimsonText-Regular.ttf') format('truetype');
                    font-weight: normal;
                    font-style: normal;
                }}
                @font-face {{
                    font-family: 'CrimsonBold';
                    src: url('fonts/crimson/Crimson_Text/CrimsonText-Bold.ttf') format('truetype');
                    font-weight: bold;
                    font-style: normal;
                }}
                body {{ font-family: 'CrimsonText', sans-serif; margin: 40px; }}
                h1, h2 {{ text-align: center; font-family: 'Oswald';}}
                h1 {{ color: #500000 }}
                dl {{ margin-bottom: 20px; }}
                dt {{ font-weight: bold; margin-top: 10px; font-family: 'CrimsonBold' }}
                dd {{ margin-left: 20px; margin-bottom: 20px;}}
                .warning {{ border-left: 4px solid #732F2f; padding-left: 10px; margin: 20px 0; }}
                .transcript {{ margin-top: 30px; }}
                .transcript p {{ margin: 2px 0; margin-bottom: 20px }}
                img {{
                    max-width: 30%;
                    height: auto;
                    display: block;
                    margin: 10px auto;
                    max-height: 100px; 
                    }}
            </style>
        </head>
        <body>
            <img src="/Users/mark.baggett/avalon-exporter/TAM-MaroonBox.png" alt="Texas A&M Logo"/>
            <h1>Texas A&amp;M University Libraries</h1>
            <h2>{self.collection_title}</h2>
            <dl>
        """

        for element, value in self.elements.items():
            if value != "":
                html += f"<dt>{element}</dt><dd>{value}</dd>"

        html += "</dl>"

        if self.warning:
            html += """
            <div class="warning">
                <strong>Disclaimer:</strong> This transcript file was initially generated using artificial intelligence.
                It is possible that there are some inaccuracies that have not yet been corrected.
            </div>
            """

        if self.transcript_lines:
            html += '<div class="transcript"><h2>Transcript</h2>'
            for line in self.transcript_lines:
                html += f"<p>{line}</p>"
            html += "</div>"

        html += "</body></html>"

        return html

    def save(self, title):
        html_content = self.build_html(title, language="en-US")
        HTML(string=html_content, base_url=os.getcwd()).write_pdf(
            self.output, pdf_tags=True,
            optimize_size=('fonts',),
            presentational_hints=True,
        )


if __name__ == "__main__":
    collection_title = 'DWG Project'

    data_from_avalon = {
        'Title': 'Interview with Linnea Glatt: Part 2',
        'Publisher': 'Art This Week Productions',
    }

    builder = HTMLPDFBuilder(
        output_filename="dwg2.pdf", 
        vtt="/Volumes/avalon_pre/dropbox/Mark_-_Test_Collection/content/dwg-project_linea-glatt_pt2.vtt",
        collection=collection_title,
        metadata=data_from_avalon
    )
    builder.save(data_from_avalon['Title'])
