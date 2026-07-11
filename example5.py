def sum_even(n):
    total = 0

    for number in range(1, n + 1):
        if number % 2 == 0:
            total += number

    return total


print(sum_even(10))
