import subprocess
from pdf2image import convert_from_path

def latex_to_image(gpt_reply, image_path="tmp/answer_image.png"):
    tex_path = generate_latex_tex(gpt_reply)
    pdf_path = compile_latex_to_pdf(tex_path)
    img_path = pdf_to_png(pdf_path, image_path)
    return img_path


def generate_latex_tex(content, tex_path="tmp/answer.tex"):
    tex_template = f"""
    \\documentclass[12pt]{{ltjsarticle}}
    \\usepackage{{amsmath}}
    \\usepackage{{amssymb}}
    \\usepackage{{bm}}
    \\usepackage{{mathtools}}
    \\usepackage{{fontspec}}
    \\setmainfont{{Noto Sans JP}}
    \\begin{{document}}
    {content}
    \\end{{document}}
    """
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(tex_template)
    return tex_path



def compile_latex_to_pdf(tex_path):
    output_dir = "tmp"
    subprocess.run(
        ["lualatex", "-output-directory", output_dir, tex_path],
        check=True
    )
    return tex_path.replace(".tex", ".pdf")


def pdf_to_png(pdf_path, image_path="tmp/answer_image.png"):
    images = convert_from_path(pdf_path)
    images[0].save(image_path, 'PNG')
    return image_path