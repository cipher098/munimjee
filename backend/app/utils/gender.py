"""
Guess gender from an Indian first name and return the appropriate address term.
"""

_FEMALE_NAMES = {
    "priya", "pooja", "neha", "sneha", "anjali", "kavya", "shruti", "divya",
    "asha", "rekha", "sunita", "geeta", "seema", "reena", "rani", "rita",
    "preeti", "usha", "anita", "meena", "deepa", "lata", "radha", "sita",
    "nisha", "ritu", "suman", "shweta", "archana", "mamta", "vandana",
    "shilpa", "swati", "jyoti", "aarti", "komal", "mansi", "renu",
    "simran", "amrita", "pallavi", "aarohi", "riya", "aisha", "zara",
    "sara", "tanvi", "ishita", "khushi", "megha", "payal", "trisha",
    "nandini", "bharti", "pushpa", "savita", "kamla", "mala", "sudha",
    "poonam", "babita", "nitu", "chanda", "chandni", "reshma", "shalini",
    "nikita", "kritika", "ritika", "anika", "namrata", "meghna", "varsha",
    "garima", "monika", "hemlata", "vidya", "lalita", "sumitra", "kalyani",
    "malati", "sarita", "kavita", "sunaina", "rupal", "hema", "uma",
    "sonal", "minal", "tejal", "hetal", "kinjal", "dhara", "poojita",
    "shreya", "prachi", "prerna", "puja", "diya", "tanya", "sanya",
    "naina", "isha", "asmita", "smita", "supriya", "sangeeta", "sangita", "sejal",
    "kiran",  # unisex but predominantly female in common usage
    "pinki", "guddi", "babli", "munni", "champa", "paro", "leela",
    "sheela", "meera", "gita", "sita", "gauri", "lakshmi", "saraswati",
    "parvati", "durga", "devi", "revati", "savitri", "gayatri", "sushma",
    "nirmala", "sharda", "shanta", "manju", "kusum", "kanta", "vimla",
    "padma", "ambika", "nalini", "vasanti", "madhuri", "manisha", "alka",
    "alisha", "alia", "sana", "hina", "noor", "zoya", "fatima", "ayesha",
    "ruhi", "mehak", "jasmine", "jasmin", "navneet", "gurpreet", "harpreet",
    "manpreet", "jaspreet", "kirandeep", "amandeep", "sukhdeep",
}

_MALE_NAMES = {
    "rahul", "rohit", "amit", "raj", "arjun", "vikas", "saurabh", "deepak",
    "suresh", "ramesh", "mahesh", "ganesh", "naresh", "dinesh", "rakesh",
    "lokesh", "mukesh", "rajesh", "umesh", "hitesh", "paresh", "nilesh",
    "manish", "satish", "prakash", "aakash", "akash", "vikash", "santosh",
    "sanjay", "ajay", "vijay", "uday", "manoj", "ravi", "shiv", "ram",
    "shyam", "mohan", "rohan", "sohan", "krishna", "vishnu", "arun",
    "varun", "tarun", "gautam", "ankit", "sumit", "mohit", "lalit",
    "sunil", "anil", "kapil", "sahil", "nikhil", "akhil", "akhilesh",
    "abhinav", "abhishek", "abhimanyu", "akshay", "aman", "amar",
    "amitabh", "amol", "anand", "aryan", "ashish", "ashok", "atul",
    "bablu", "babu", "bharat", "chetan", "devraj", "dhananjay", "dhruv",
    "digvijay", "dilip", "gaurav", "gopal", "hardik", "harish", "hemant",
    "hiren", "ishan", "ishaan", "jagdish", "jai", "jayesh", "jitendra",
    "kalpesh", "kamal", "kanhaiya", "karan", "kartik", "kishore",
    "krishan", "kunal", "kundan", "lakhan", "madhav", "mahendra", "manav",
    "manohar", "mayank", "mihir", "milan", "neeraj", "nitin", "omkar",
    "paras", "parth", "piyush", "pranav", "prashant", "prateek", "pritam",
    "pushkar", "rajan", "rajiv", "rajkumar", "rajnish", "raju", "ranbir",
    "ranjit", "ranvir", "rashid", "ratan", "ratnesh", "ravindra", "ritesh",
    "riyaz", "sachin", "samarth", "sameer", "sanjeev", "sanjiv",
    "shailesh", "shekhar", "shreyas", "siddharth", "soham", "sonu",
    "sudhir", "suraj", "surendra", "tejvir", "ujjwal", "vatsal", "vedant",
    "vikram", "vipin", "vishal", "vishwas", "vivek", "yash", "yogesh",
    "girish", "brijesh", "devesh", "kamlesh", "rupesh", "haresh",
    "pradeep", "praveen", "naveen", "pawan", "chandan", "nandan",
    "shubham", "shubh", "harsh", "pankaj", "viraj", "veer", "aarav",
    "rehan", "zaid", "faiz", "arsh", "gurjot", "gurpreet", "manjot",
    "jaspreet", "navjot", "lovepreet", "harjot", "eklavya", "chandrashekhar",
    "bhuvanesh", "ramakant", "ramanuj", "ramlal", "ramesh", "ratan",
    "devansh", "divyansh", "priyansh", "utkarsh", "adarsh", "aayush",
    "ayush", "sarthak", "saransh", "vansh", "tanish", "manit",
}


def guess_gender(full_name: str) -> str:
    """Return 'male', 'female', or 'unknown' for a given name."""
    if not full_name:
        return "unknown"
    first = full_name.strip().split()[0].lower()
    if first in _FEMALE_NAMES:
        return "female"
    if first in _MALE_NAMES:
        return "male"
    return "unknown"


def address_term(gender: str) -> str:
    return "madam" if gender == "female" else "yaar"


async def guess_gender_ai(full_name: str) -> str:
    """Use Claude Haiku to guess gender when the name lookup returns 'unknown'."""
    import anthropic
    from app.config import settings

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
        messages=[{
            "role": "user",
            "content": (
                f"Is the Indian name '{full_name}' typically male or female? "
                "Reply with exactly one word: male, female, or unknown."
            ),
        }],
    )
    result = response.content[0].text.strip().lower()
    if result in ("male", "female"):
        return result
    return "unknown"
