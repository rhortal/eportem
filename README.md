# ePortem

Scripts for ePortem. Automates start (office and home versions), lunch, return and end of day.

ePortem is a SaaS solution used in Spain for HR-related tasks. These scripts automate the functionality that enables people to track the time they spend at work every day, as required by Spanish law.



## Deployment

To deploy this project, clone this repo and make sure you have the python3 binay in your PATH.
Takes ePortem and Telegram credentials from a file. 
- Copy config/credentials-example.txt to config/credentials.txt and add you DNI and Password in 2 lines, replacing the example. On the third line, write 
YES for headless operation (preferred) and NO if you want to see what the browser is doing (useful for debugging).
- Copy config/telegram-example.txt to config/telegram.txt. If you want to send telegram messages, make the first line YES and add you Bot Token and Chat ID in the 2 following lines, as in the example.

## Usage/Examples

There are 2 ways to use the software:

- For interactive use on a Mac, drag the *command* folder to your Dock and set it to fan, so you can select which one to click easily from the Dock.

- For programmatic use simply call the Python files with `python3 /full_path/filename.py` from your command line.

### Automation
You can set these scripts to run automatically using Unix `cron`. You can also add a `sleep $[RANDOM\%nn]m` command preceding the call so the command is called at a random time between 0 and nn minutes.
```
55 08 * * 1-4 sleep $[RANDOM\%10]m ; python3 /full_path/start_the_day.py
55 08 * * 5 sleep $[RANDOM\%10]m ; python3 /full_path/start_the_day_home.py
25 13 * * 1-5 sleep $[RANDOM\%10]m ; python3 /full_path/lunch_break.py
25 14 * * 1-4 sleep $[RANDOM\%10]m ; python3 /full_path/after_lunch_break.py
25 14 * * 5 sleep $[RANDOM\%10]m ; python3 /full_path/after_lunch_break_home.py
10 18 * * 1-5 sleep $[RANDOM\%25]m ;python3 /full_path/stop_the_day.py
```
The above example checks in Monday to Thursday between 08:55 and 09:05 at the office, and at the same time Fridays starts work from home.
It then notifies of lunch starting 13:25-13:35 and returns 14:25-14:35 (Fridays it uses the return to work from home script).
It finally calls the script to end the day daily between 18:10 and 18:35.

## Acknowledgements

 - ChatGPT 3.5
 - XPath Helper Chrome extension
 - The Selenium docs


## 🚀 About Me
I'm learning Python and exploring ways to automate daily tasks at work as a way to improve my Python skills.
