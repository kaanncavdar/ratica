import pytest

from ratica.detect import detect_language

SAMPLES = {
    "en": "The engine reads the book and writes the translation back into the pages that the reader sees.",
    "tr": "Bu kitap bilgisayarda çalışan bir model ile çevrilir ve sayfa düzeni olduğu gibi korunur.",
    "de": "Das Programm liest das Buch und schreibt die Übersetzung in die Seiten, die der Leser sieht.",
    "fr": "Le programme lit le livre et écrit la traduction dans les pages que le lecteur voit.",
    "es": "El programa lee el libro y escribe la traducción en las páginas que ve el lector.",
    "it": "Il programma legge il libro e scrive la traduzione nelle pagine che il lettore vede.",
    "pt": "O programa lê o livro e escreve a tradução nas páginas que o leitor vê.",
    "nl": "Het programma leest het boek en schrijft de vertaling in de pagina's die de lezer ziet.",
    "pl": "Program czyta książkę i zapisuje tłumaczenie na stronach, które widzi czytelnik.",
    "ru": "Программа читает книгу и записывает перевод на страницы, которые видит читатель.",
    "uk": "Програма читає книгу і записує переклад на сторінки, які бачить читач.",
    "el": "Το πρόγραμμα διαβάζει το βιβλίο και γράφει τη μετάφραση στις σελίδες.",
    "ja": "このプログラムは本を読み、翻訳をページに書き戻します。",
    "zh": "这个程序读取书籍并把译文写回原来的页面。",
    "ko": "이 프로그램은 책을 읽고 번역을 원래 페이지에 다시 씁니다.",
    "ro": "Programul citește cartea și scrie traducerea în paginile pe care le vede cititorul.",
    "cs": "Program čte knihu a zapisuje překlad do stránek, které čtenář vidí.",
    "sv": "Programmet läser boken och skriver översättningen på sidorna som läsaren ser.",
    "id": "Program ini membaca buku dan menulis terjemahan ke halaman yang dilihat pembaca.",
    "vi": "Chương trình đọc cuốn sách và viết bản dịch vào các trang mà người đọc nhìn thấy.",
    "az": "Proqram kitabı oxuyur və tərcüməni oxucunun gördüyü səhifələrə yazır.",
    "bg": "Програмата чете книгата и записва превода в страниците, които читателят вижда.",
    "hi": "यह प्रोग्राम किताब पढ़ता है और अनुवाद को पन्नों में लिखता है।",
}


@pytest.mark.parametrize("code", sorted(SAMPLES))
def test_the_language_of_a_text_is_detected(code):
    assert detect_language(SAMPLES[code] * 3) == code


def test_numbers_and_symbols_alone_give_no_answer():
    assert detect_language("12 + 34 = 46 ... 1.2 3.4") is None
