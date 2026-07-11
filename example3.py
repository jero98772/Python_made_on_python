# def is_palindrome(text):
#    return text == text[::-1]


def is_palindrome(text):
    left = 0
    right = len(text) - 1

    while left < right:
        if text[left] != text[right]:
            return False
        left += 1
        right -= 1

    return True


print(is_palindrome("racecar"))  # True
print(is_palindrome("python"))  # False
print(is_palindrome("Ana"))  # True
