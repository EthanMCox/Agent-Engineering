# Notes from experiments

I tried having it generate different a paragraph in different styles and it succeeded with one prompt. 

I tried giving it conflicting instructions (to list prime numbers from 0 to 41 without listing any composite numbers, and to list all even numbers frm 0 to 40, all in one list) and ran the program a few times. I found that the model was able to identify that the instructions were conflicting in every instance. Sometimes it tried to make a best effort, and other times it denied completing the task. 

I tried having the model generate a couple sentences in each of the 107 top languages. With gpt 5 nano, it mentioned that it was a large request and asked for confirmation before continuing. However, with gpt 5, it proceeded directly with the request, 80 seconds and 200 seconds to complete across two runs (I adjusted the prompt the second time). I found that there were 21 languages which the model did not know.

Using the output of the previous prompt, I experimented with whether the model was able to correctly count how many languages the model did not know. I ran the model a few times and got output of 17, 18, and 19 twice. In other words, the model was both inconsistent and wrong every time. 

I had the model generate key world events in each quarter for each year from 2020 to 2026. Across several different models, data from 2025 onward was consistently unavailable, though 2024 had data. 

I tried writing a prompt with no spaces, and it did a good job of interpreting the instructions and completing them correctly. 

# Reflection and Takeaways
It was really interesting poking around some of the capabilities of the AI models in a more focused way. While it was able to do some things really well, I was most interested in identifying the limitations of these models—not being able to count effectively, having no data on certain languages, only being trained through 2024, etc. 