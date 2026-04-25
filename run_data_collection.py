from collect_openalex import (
    collect_openalex_first_order,
    collect_openalex_second_order,
    collect_openalex_second_order_ov_first_order,
)

from collect_altmetric import (
    collect_altmetric_first_order,
    collect_altmetric_second_order_oa_first_order,
    collect_altmetric_second_order_ov_first_order,
)

from collect_overton import (
    collect_overton_first_order,
    collect_overton_second_order,
    collect_overton_second_order_oa_first_order,
    collect_overton_second_order_alt_first_order,
)


def run_data_collection():
    print("Running data collection pipeline...\n")

    print("Step 1: OpenAlex first-order")
    collect_openalex_first_order()

    print("\nStep 2: Altmetric first-order")
    collect_altmetric_first_order()

    print("\nStep 3: Overton first-order")
    collect_overton_first_order()

    print("\nStep 4: Overton second-order")
    collect_overton_second_order()

    print("\nStep 5: OpenAlex second-order")
    collect_openalex_second_order()

    print("\nStep 6: Altmetric second-order for OpenAlex first-order")
    collect_altmetric_second_order_oa_first_order()

    print("\nStep 7: Overton second-order for OpenAlex first-order")
    collect_overton_second_order_oa_first_order()

    print("\nStep 8: Overton second-order for Altmetric first-order")
    collect_overton_second_order_alt_first_order()

    print("\nStep 9: Altmetric second-order for Overton first-order")
    collect_altmetric_second_order_ov_first_order()

    print("\nStep 10: OpenAlex second-order for Overton first-order")
    collect_openalex_second_order_ov_first_order()


# Optional: allow standalone use too
if __name__ == "__main__":
    run_data_collection()