_NON_SINGULAR_ENDINGS = ("ss", "us", "is", "ics")


def split_identifier(text: str) -> tuple[str, ...]:
    """`debitAccount.id` -> (debit, account, id); `IBANNumber` -> (iban, number); `montantDébit` -> (montant, débit).

    Words break at any non-alphanumeric character, at lower-to-upper case changes, between
    letters and digits, and before the last capital of an acronym followed by lower case.
    Works for any alphabet, not only ASCII.
    """
    words: list[str] = []
    current = ""
    for index, char in enumerate(text):
        if not char.isalnum():
            words.append(current)
            current = ""
            continue
        previous = current[-1] if current else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        starts_word = previous and (
            (previous.islower() and char.isupper())
            or (previous.isdigit() != char.isdigit())
            or (previous.isupper() and char.isupper() and following.islower())
        )
        if starts_word:
            words.append(current)
            current = ""
        current += char
    words.append(current)
    return tuple(word.lower() for word in words if word)


def singularize(word: str) -> str:
    if len(word) <= 2 or word.endswith(_NON_SINGULAR_ENDINGS):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "uses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word
