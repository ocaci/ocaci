#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import frontmatter
import glob
import os
import argparse
import sys


def fetch_profile_data(username):
    # Use a session to preserve cookies (including __csrf)
    session = requests.Session()
    resp = session.get(f"https://iq.aws.amazon.com/e/{username}")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_token = soup.find("meta", {"name": "csrf-token"}).get("content", "")

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
    return {
        "name": result.get("displayName", ""),
        "bio": result.get("biography", ""),
        "tagline": result.get("firmName", ""),
        "location": result.get("firmCountryCode", ""),
        "hourlyRateMin": result.get("hourlyPriceMin", {}).get("value", ""),
        "hourlyRateMax": result.get("hourlyPriceMax", {}).get("value", ""),
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

    for file in files:
        post = frontmatter.load(file)
        iq_profile = post.get('iqProfile')
        # Normalize iqProfile to expert ID if a full URL is provided
        change_iq_profile = False
        if iq_profile.startswith("http://") or iq_profile.startswith("https://"):
            # Extract the last path segment as the username
            username = iq_profile.rstrip("/").split("/")[-1]
            post['iqProfile'] = username
            iq_profile = username
            change_iq_profile = True
        if not iq_profile:
            print(f"ERROR: Missing 'iqProfile' field in {file}")
            sys.exit(1)
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
                    frontmatter.dump(post, f)
                print(f"Updated {file}")
        except Exception as e:
            print(f"ERROR: Failed to fetch profile for {file} ({iq_profile}): {e}")
            sys.exit(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sync AWS IQ profile data into Hugo front-matter")
    parser.add_argument('--files', nargs='+', help='List of Markdown files to sync')
    args = parser.parse_args()
    main(target_files=args.files) 
