#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import frontmatter
import glob
import os
import argparse
import sys
import traceback


def fetch_profile_data(username):
    # Use a session to preserve cookies (including __csrf)
    session = requests.Session()
    # Spoof a browser User-Agent so AWS IQ returns the CSRF token in the HTML
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36"
    })
    resp = session.get(f"https://iq.aws.amazon.com/e/{username}")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    tag = soup.find("meta", {"name": "csrf-token"})
    if tag is None:
        raise RuntimeError(
            f"No CSRF token meta tag found for user {username}. Fetched HTML snippet: {resp.text[:200]!r}"
        )
    csrf_token = tag.get("content", "")

    # Set session headers for GraphQL call
    session.headers.update({
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf_token
    })

    # GraphQL endpoint and query
    endpoint = "https://iq.aws.amazon.com/graphql?sif_profile=aiq"
    PUBLIC_EXPERT_PROFILE_QUERY = """query PublicExpertProfile($expertId: ID!) {
  expertProfile(profileId: $expertId) {
    ...PublicExpertProfile
  }
}

fragment PublicExpertProfile on ExpertProfile {
  displayName
  biography
  firmName
  firmCountryCode
  hourlyPriceMin { value }
  hourlyPriceMax { value }
  ratingsTotal
  numberOfReviews
  profilePictureUrl
  awsCertifications { edges { node { certificationName } } }
  reviews { edges { node { id comment date rating } } }
}
"""
    payload = [{
        "operationName": "PublicExpertProfile",
        "variables": {"expertId": username},
        "query": PUBLIC_EXPERT_PROFILE_QUERY
    }]
    # Execute GraphQL via session (which includes cookies and headers)
    gql_resp = session.post(endpoint, json=payload)
    gql_resp.raise_for_status()
    result = gql_resp.json()[0]["data"]["expertProfile"]

    # Map response to our fields
    aws_certs = [edge["node"]["certificationName"] for edge in result.get("awsCertifications", {}).get("edges", [])]
    reviews = [
        {"id": edge["node"].get("id", ""),
         "comment": edge["node"].get("comment", ""),
         "date": edge["node"].get("date", ""),
         "rating": edge["node"].get("rating", "")} 
        for edge in result.get("reviews", {}).get("edges", [])
    ]
    # Safely extract hourly price values, handling None cases
    hourly_min = result.get("hourlyPriceMin")
    hourly_max = result.get("hourlyPriceMax")
    hourly_min_value = hourly_min.get("value") if hourly_min else ""
    hourly_max_value = hourly_max.get("value") if hourly_max else ""

    return {
        "name": result.get("displayName", ""),
        "bio": result.get("biography", ""),
        "tagline": result.get("firmName", ""),
        "location": result.get("firmCountryCode", ""),
        "hourlyRateMin": hourly_min_value,
        "hourlyRateMax": hourly_max_value,
        "profilePicture": result.get("profilePictureUrl", ""),
        "rating": result.get("ratingsTotal", ""),
        "numberOfReviews": result.get("numberOfReviews", ""),
        "awsCertifications": aws_certs,
        "reviews": reviews
    }


def main(target_files=None):
    script_dir = os.path.dirname(__file__)
    root_dir = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir))
    pattern = os.path.join(root_dir, 'content', 'consultants', '*.md')
    default_files = glob.glob(pattern)
    files = target_files if target_files else default_files

    # Skip special files that don't have consultant profiles
    skip_files = ['_index.md']
    files = [f for f in files if os.path.basename(f) not in skip_files]

    for file in files:
        # Load front-matter directly from file
        post = frontmatter.load(file)
        iq_profile = post.get('iqProfile')
        # Ensure iqProfile exists before normalizing
        if not iq_profile:
            print(f"ERROR: Missing 'iqProfile' field in {file}")
            sys.exit(1)
        # Normalize iqProfile to expert ID if a full URL is provided
        change_iq_profile = False
        if iq_profile.startswith("http://") or iq_profile.startswith("https://"):
            # Extract the last path segment as the username
            username = iq_profile.rstrip("/").split("/")[-1]
            post['iqProfile'] = username
            iq_profile = username
            change_iq_profile = True
        try:
            data = fetch_profile_data(iq_profile)
            aws_certifications = data['awsCertifications']
            location = data['location']
            name = data['name']
            tagline = data['tagline']
            bio = data['bio']
            hourly_rate_min = data.get('hourlyRateMin', '')
            hourly_rate_max = data.get('hourlyRateMax', '')
            profile_picture = data['profilePicture']
            rating = data['rating']
            number_of_reviews = data.get('numberOfReviews', '')
            reviews = data['reviews']
            # Initialize updated flag, respect any iqProfile normalization change
            updated = change_iq_profile

            # update front-matter fields
            if post.get('awsCertifications') != aws_certifications:
                post['awsCertifications'] = aws_certifications
                updated = True
            if post.get('location') != location:
                post['location'] = location
                updated = True
            # Ensure locations taxonomy matches location
            if post.get('locations') != [location]:
                post['locations'] = [location]
                updated = True
            # new fields
            if post.get('name') != name:
                post['name'] = name
                updated = True
            if post.get('tagline') != tagline:
                post['tagline'] = tagline
                updated = True
            if post.get('bio') != bio:
                post['bio'] = bio
                updated = True
            if post.get('profilePicture') != profile_picture:
                post['profilePicture'] = profile_picture
                updated = True
            if post.get('rating') != rating:
                post['rating'] = rating
                updated = True
            if post.get('numberOfReviews') != number_of_reviews:
                post['numberOfReviews'] = number_of_reviews
                updated = True
            if post.get('hourlyRateMin') != hourly_rate_min:
                post['hourlyRateMin'] = hourly_rate_min
                updated = True
            if post.get('hourlyRateMax') != hourly_rate_max:
                post['hourlyRateMax'] = hourly_rate_max
                updated = True
            if post.get('reviews') != reviews:
                post['reviews'] = reviews
                updated = True

            if updated:
                with open(file, 'w', encoding='utf-8') as f:
                    # Serialize front-matter and content as string
                    f.write(frontmatter.dumps(post))
                print(f"Updated {file}")
        except Exception as e:
            traceback.print_exc()
            print(f"ERROR: Failed to fetch profile for {file} ({iq_profile}): {e}")
            sys.exit(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sync AWS IQ profile data into Hugo front-matter")
    parser.add_argument('--files', nargs='+', help='List of Markdown files to sync')
    args = parser.parse_args()
    main(target_files=args.files) 
