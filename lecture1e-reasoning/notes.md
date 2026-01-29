- Gave openai permission for summaries
- fermi problem
   - Honestly pretty impressed with how well it reasoned and gave bounds. 

- Tried giving a simple riddle and stating to provide the answer before giving reasoning. It was interesting because although the actual output followed those instructions, the reasoning still happened behind the scenes, which makes it seem like the actual instructions to do reasoning before or after may not make as much sense to include when the reasoning will still do it. 
- Tried some fractional math problems and although it got the right answer, some of the reasoning was completely off base, such as thinking that 7 times as much could mean either multiplying by 7 or adding the original amount to seven times the original amount. 
- When I asked about the chair, it thought I had image mode enabled even though I did not. 
- Reasoning exposes a lot of flawed logic that you don't see in the normal output. 
- Stacking non-stackable objects, it realizes that it is not very easy to do so
- When asking about the president of the United States, it didn't have any reasoning on the low models but had some reasoning for the medium complexity model. 
- Medium reasoning model gave decent tips for food but especially performed better when asking for an improvement on one particular recipe. The low reasoning model didn't do much reasoning at all and the recipe definitely wasn't as good either. 


### Cost differences
Low:
- Input 209
- Cached 0
- Output 1800
- Reasoning 1472
- Cost $0.000730

Medium:
- Input 209
- Cached 0
- Output 3445
- Reasoning 3264
- Cost $0.001388

High
- Input 209
- Cached 0
- Output 9876
- Reasoning 9664
- Cost $0.003961

Ethics:

Low: 
- 83
- 0
- 829
- 448
- $0.000336

Medium:
- 83
- 0
- 3323
- 3008
- $0.001333

High:
- 83
- 0
- 10039
- 9664
- $0.004020