# Sample data for this API

Method: ```POST```

URL: ```http://localhost:18899/api/generateVariant```

Headers:
```
Authorization: Bearer 9786534210
Content-Type: application/json
```

Request body:

```
{
    "question":"If there are no lanes marked on the road, you should drive - Near to the left-hand side of the road.- Anywhere on your side of the road.- Along the middle of the road.",
    "num":2
}
```

Reponse:

```
{
    "knowledge_point_name": "Position on an Unmarked Road",
    "knowledge_point_summary": "When driving on a road without marked lanes in Australia, drivers must keep close to the left-hand side of their side of the road so as to allow safe passing, maintain traffic flow and comply with road rules requiring left-side driving.",
    "variant_questions": [
        {
            "prompt": "You are driving on a two-way road that has no painted lane lines. Where should you position your vehicle?",
            "option_a": "Near to the left-hand side of the road",
            "option_b": "Centered on the roadway",
            "option_c": "Near to the right-hand side of the road",
            "option_d": "Directly in the middle so you can see both directions",
            "correct_option": "A",
            "explanation": "On unmarked roads in Australia you must keep as close as practicable to the left-hand side of your side of the road to allow safe passing and comply with left-side driving rules."
        },
        {
            "prompt": "On a road without lane markings, what is the proper position for your vehicle when travelling?",
            "option_a": "Close to the left-hand edge of your side of the road",
            "option_b": "Along the exact centre of the road",
            "option_c": "Close to the right-hand edge of the road",
            "option_d": "Swerving between edges to avoid parked cars",
            "correct_option": "A",
            "explanation": "Drivers must keep to the left side of the road where there are no marked lanes; staying near the left-hand edge ensures safety and compliance with left-side driving laws."
        }
    ],
    "time": 8385,
    "usage": {
        "input_tokens": 288,
        "output_tokens": 428,
        "reasoning_tokens": 64,
        "total_tokens": 716
    }
}
```
